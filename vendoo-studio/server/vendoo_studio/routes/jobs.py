from __future__ import annotations

import asyncio
import copy
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from pathlib import Path

from vendoo_studio.database import get_db
from vendoo_studio.repositories.queries import JobRepo, ConversationRepo, ListingRepo, FillLogRepo
from vendoo_studio.config import PHOTOS_DIR
from vendoo_studio.models.conversation import Photo

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobResponse(BaseModel):
    id: str
    conversation_id: str
    status: str
    current_step: str | None
    vendoo_item_id: str | None
    vendoo_url: str | None
    attempt_count: int
    last_error: str | None
    listing_title: str
    mode: str | None = None
    created_at: str
    updated_at: str


class CreateJobRequest(BaseModel):
    conversation_id: str
    confirm_overwrite: bool = False


class FillFieldItem(BaseModel):
    id: str | None = None
    marketplace: str | None = None
    field: str | None = None
    value: str | None = None
    selector: str | None = None


class FillFieldsRequest(BaseModel):
    fields: list[FillFieldItem]


@router.post("", response_model=JobResponse)
async def create_job(body: CreateJobRequest, db: Session = Depends(get_db)):
    conv_repo = ConversationRepo(db)
    conv = conv_repo.get(body.conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    listing_repo = ListingRepo(db)
    revisions = listing_repo.get_revisions(body.conversation_id)
    if not revisions:
        raise HTTPException(400, "No listing to approve. Generate or edit a listing first.")

    latest_revision = revisions[0]
    photo_count = len(conv_repo.get_photos(body.conversation_id))

    from vendoo_studio.services.vendoo_import import vendoo_binding
    from vendoo_studio.models.validation import validate_listing
    from vendoo_studio.services.marketplaces import (
        selected_fillable_platforms,
        unsupported_in_selection,
        get_selected_marketplaces,
        marketplace_label,
    )
    listing_snapshot = _prepare_listing_snapshot(db, conv, latest_revision.listing_json)
    binding = vendoo_binding(conv.notes)
    # Pre-dispatch guard: unsupported markets never enter the approved job snapshot.
    selected_now = get_selected_marketplaces()
    blocked = unsupported_in_selection(selected_now)
    if blocked:
        labels = ", ".join(marketplace_label(item_id) for item_id in blocked)
        raise HTTPException(
            400,
            f"{labels} cannot be selected for Send — automation is not available. "
            "Deselect unsupported marketplaces before creating a job.",
        )
    listing_snapshot["platforms"] = selected_fillable_platforms(selected_now)
    validation = validate_listing(
        listing_snapshot,
        photo_count,
        require_photos=True,
        selected_marketplaces=listing_snapshot["platforms"],
    )
    if not validation.can_send:
        raise HTTPException(400, _validation_error_detail(validation))

    existing_item_id = str(binding.get("vendooItemId") or "").strip()
    if existing_item_id and existing_item_id.lower() != "new" and not body.confirm_overwrite:
        raise HTTPException(
            409,
            "This listing is already bound to a Vendoo draft. Confirm overwrite to update that draft.",
        )

    active = JobRepo(db).get_active()
    if active:
        raise HTTPException(409, "Another job is already in progress")

    approved_revision = listing_repo.save_revision(
        conv_id=body.conversation_id,
        listing_json=listing_snapshot,
        source="normalized",
        parent_revision_id=latest_revision.id,
    )
    conv_repo.update_status(body.conversation_id, "listing")

    job_repo = JobRepo(db)
    job = job_repo.create(
        conv_id=body.conversation_id,
        approved_revision_id=approved_revision.id,
        listing_snapshot=listing_snapshot,
        vendoo_item_id=binding.get("vendooItemId"),
        vendoo_url=binding.get("vendooUrl"),
    )
    job_repo.add_event(job.id, "created", "queued")

    from vendoo_studio.routes.extension import dispatch_queued_jobs
    await dispatch_queued_jobs()

    return _job_response(job)


@router.get("", response_model=list[JobResponse])
def list_jobs(db: Session = Depends(get_db)):
    repo = JobRepo(db)
    return [_job_response(j) for j in repo.list_all()]


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Session = Depends(get_db)):
    repo = JobRepo(db)
    job = repo.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_response(job)


@router.get("/{job_id}/events")
def get_job_events(job_id: str, db: Session = Depends(get_db)):
    repo = JobRepo(db)
    job = repo.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    events = repo.get_events(job_id)
    return [
        {
            "id": e.id,
            "sequence": e.sequence,
            "event_type": e.event_type,
            "step": e.step,
            "payload": e.payload,
            "created_at": e.created_at.isoformat() if e.created_at else "",
        }
        for e in events
    ]


@router.get("/{job_id}/preview")
async def stream_job_preview(job_id: str, db: Session = Depends(get_db)):
    repo = JobRepo(db)
    job = repo.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    from vendoo_studio.services.preview_hub import preview_hub

    async def events():
        queue = await preview_hub.subscribe(job_id)
        try:
            yield ": connected\n\n"
            while True:
                try:
                    frame = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(frame)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            await preview_hub.unsubscribe(job_id, queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{job_id}/fill-log")
def get_job_fill_log(job_id: str, db: Session = Depends(get_db)):
    repo = JobRepo(db)
    job = repo.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    from vendoo_studio.services.fill_log import FillLogService
    return FillLogService(db).report_for_job(job)


class VendooItemResponse(BaseModel):
    ok: bool
    source: str | None = None
    item_id: str | None = None
    url: str | None = None
    error: str | None = None
    api_error: str | None = None
    item: dict | None = None
    form: dict | None = None
    statuses: dict | None = None


@router.post("/{job_id}/vendoo-item", response_model=VendooItemResponse)
async def get_vendoo_item(
    job_id: str,
    refresh: bool = False,
    cache_only: bool = False,
    db: Session = Depends(get_db),
):
    import uuid

    from vendoo_studio.routes.extension import (
        VENDOO_GET_TIMEOUT_SEC,
        dispatch_vendoo_get,
        extension_manager,
    )

    repo = JobRepo(db)
    job = repo.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not job.vendoo_url and not job.vendoo_item_id:
        binding_id = None
        binding_url = None
        from vendoo_studio.services.vendoo_import import vendoo_binding
        conv = ConversationRepo(db).get(job.conversation_id)
        if conv:
            binding = vendoo_binding(conv.notes)
            binding_id = binding.get("vendooItemId")
            binding_url = binding.get("vendooUrl")
        if binding_id or binding_url:
            job.vendoo_item_id = binding_id or job.vendoo_item_id
            job.vendoo_url = binding_url or job.vendoo_url
            db.commit()
            db.refresh(job)
        else:
            raise HTTPException(400, "No Vendoo draft is available yet. Import or send the listing first.")

    cached = repo.get_vendoo_draft(job_id)
    if cached and not refresh:
        return VendooItemResponse(
            ok=True,
            source=cached.get("source") or "cache",
            item_id=cached.get("item_id") or job.vendoo_item_id,
            url=cached.get("url") or job.vendoo_url,
            error=None,
            api_error=None,
            item=cached.get("item"),
            form=cached.get("form"),
            statuses=cached.get("statuses"),
        )

    if cache_only:
        return VendooItemResponse(
            ok=False,
            source="cache",
            item_id=job.vendoo_item_id,
            url=job.vendoo_url,
            error="No cached Vendoo draft",
            api_error=None,
            item=None,
            form=None,
            statuses=None,
        )

    if not extension_manager.connected:
        if refresh:
            raise HTTPException(400, "Chrome is not connected")
        if cached:
            return VendooItemResponse(
                ok=True,
                source=cached.get("source") or "cache",
                item_id=cached.get("item_id") or job.vendoo_item_id,
                url=cached.get("url") or job.vendoo_url,
                error=None,
                api_error=None,
                item=cached.get("item"),
                form=cached.get("form"),
                statuses=cached.get("statuses"),
            )
        raise HTTPException(400, "Chrome is not connected")

    request_id = uuid.uuid4().hex[:12]
    waiter = extension_manager.register_wait(request_id)
    try:
        sent = await dispatch_vendoo_get(job, request_id)
        if not sent:
            raise HTTPException(503, "Could not reach the Chrome extension")
        try:
            payload = await asyncio.wait_for(waiter, timeout=VENDOO_GET_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            raise HTTPException(
                504,
                "Chrome did not return the Vendoo draft in time. Open the listing tab and try again.",
            )
    finally:
        extension_manager.cancel_wait(request_id)

    if not payload.get("ok"):
        # Explicit refresh must not silently re-serve a stale draft — that makes
        # Fields keep showing empty counts after Fill / Refresh.
        if refresh:
            raise HTTPException(502, payload.get("error") or "Could not refresh the Vendoo draft")
        if cached:
            return VendooItemResponse(
                ok=True,
                source=cached.get("source") or "cache",
                item_id=cached.get("item_id") or job.vendoo_item_id,
                url=cached.get("url") or job.vendoo_url,
                error=payload.get("error"),
                api_error=payload.get("api_error"),
                item=cached.get("item"),
                form=cached.get("form"),
                statuses=cached.get("statuses"),
            )
        raise HTTPException(502, payload.get("error") or "Could not read the Vendoo draft")

    statuses = payload.get("statuses")
    if not isinstance(statuses, dict):
        form = payload.get("form")
        statuses = form.get("statuses") if isinstance(form, dict) else None
        if not isinstance(statuses, dict):
            statuses = None

    repo.save_vendoo_draft(
        job.id,
        item=payload.get("item"),
        form=payload.get("form"),
        item_id=payload.get("item_id") or job.vendoo_item_id,
        url=payload.get("url") or job.vendoo_url,
        source=payload.get("source") or "live",
        step=job.current_step,
        statuses=statuses,
    )

    return VendooItemResponse(
        ok=True,
        source=payload.get("source"),
        item_id=payload.get("item_id") or job.vendoo_item_id,
        url=payload.get("url") or job.vendoo_url,
        error=payload.get("error"),
        api_error=payload.get("api_error"),
        item=payload.get("item"),
        form=payload.get("form"),
        statuses=statuses,
    )


class ResolveCategoryRequest(BaseModel):
    query: str | None = None


class ResolveCategoryResponse(BaseModel):
    ok: bool
    query: str | None = None
    path: str | None = None
    matches: list[dict] = Field(default_factory=list)
    error: str | None = None


@router.post("/{job_id}/resolve-category", response_model=ResolveCategoryResponse)
async def resolve_category(
    job_id: str,
    body: ResolveCategoryRequest = ResolveCategoryRequest(),
    db: Session = Depends(get_db),
):
    from vendoo_studio.routes.extension import extension_manager
    from vendoo_studio.services.category_lookup import resolve_listing_category

    repo = JobRepo(db)
    job = repo.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not job.vendoo_url and not job.vendoo_item_id:
        raise HTTPException(400, "No Vendoo draft is available yet. Import or send the listing first.")
    if not extension_manager.connected:
        raise HTTPException(400, "Chrome is not connected")
    if job.status == "dispatched" and job.current_step == "filling_fields":
        raise HTTPException(409, "A Vendoo fill is already running.")

    result = await resolve_listing_category(
        db,
        job.conversation_id,
        query=(body.query if body else None),
        job=job,
    )
    if result.get("skipped"):
        raise HTTPException(400, result.get("error") or "Could not search Vendoo categories")
    if not result.get("ok"):
        status = 504 if "in time" in str(result.get("error") or "") else 502
        raise HTTPException(status, result.get("error") or "No matching Vendoo category")
    return ResolveCategoryResponse(
        ok=True,
        query=result.get("query"),
        path=result.get("path"),
        matches=result.get("matches") or [],
    )


class OpenListingResponse(BaseModel):
    ok: bool
    url: str
    via: str


@router.post("/{job_id}/open", response_model=OpenListingResponse)
async def open_listing(job_id: str, db: Session = Depends(get_db)):
    from vendoo_studio.routes.extension import dispatch_open_listing, extension_manager
    from vendoo_studio.services.chrome_bridge import ChromeBridgeError, launch_studio_chrome, listing_url_for_job

    repo = JobRepo(db)
    job = repo.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    url = listing_url_for_job(job.vendoo_item_id, job.vendoo_url)
    if not url:
        raise HTTPException(400, "No Vendoo draft is available yet. Send the listing first.")

    if extension_manager.connected:
        sent = await dispatch_open_listing(job)
        if sent:
            return OpenListingResponse(ok=True, url=url, via="extension")

    try:
        launch_studio_chrome(url, visible=True)
    except ChromeBridgeError as exc:
        raise HTTPException(400, str(exc)) from exc
    return OpenListingResponse(ok=True, url=url, via="chrome")


@router.post("/{job_id}/fill-fields", response_model=JobResponse)
async def fill_job_fields(job_id: str, body: FillFieldsRequest, db: Session = Depends(get_db)):
    from vendoo_studio.models.job import ACTIVE_JOB_STATUSES
    from vendoo_studio.routes.extension import dispatch_fill_fields, extension_manager
    from vendoo_studio.services.fill_log import (
        FILLABLE_STATUSES,
        MAX_FILL_FIELDS,
        MAX_PATCH_VALUE,
        FillLogService,
        field_lookup_key,
        listing_value_for_field,
        normalize_field_label,
        preview_value,
        write_values_into_listing,
    )
    from vendoo_studio.services.registry import SELLER_SETTING_LABELS

    repo = JobRepo(db)
    job = repo.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status in ACTIVE_JOB_STATUSES:
        raise HTTPException(400, "Wait for the current fill to finish")
    active = [item for item in JobRepo(db).get_active() if item.id != job.id]
    if active:
        raise HTTPException(409, "Another job is already in progress")
    if job.status not in {"completed", "failed"}:
        raise HTTPException(400, f"Job is {job.status}, cannot fill leftover fields")
    if not job.vendoo_url and not job.vendoo_item_id:
        raise HTTPException(400, "No Vendoo draft is available yet. Send the listing first.")
    if not extension_manager.connected:
        raise HTTPException(400, "Chrome is not connected")

    requested = body.fields[:MAX_FILL_FIELDS]
    if not requested:
        raise HTTPException(400, "Add at least one field to fill")

    listing_repo = ListingRepo(db)
    revisions = listing_repo.get_revisions(job.conversation_id)
    listing = dict(revisions[0].listing_json) if revisions else dict(job.listing_snapshot or {})

    fill_repo = FillLogRepo(db)
    existing_ids = [str(item.id or "").strip() for item in requested if str(item.id or "").strip()]
    existing_by_id = {
        entry.id: entry
        for entry in fill_repo.get_for_job_ids(job_id, existing_ids)
    }

    resolved: list[dict] = []
    created_specs: list[dict] = []
    for item in requested:
        entry_id = str(item.id or "").strip()
        marketplace = str(item.marketplace or "").strip().lower()
        field = str(item.field or "").strip()
        selector = str(item.selector or "").strip()
        value = str(item.value or "").strip()
        entry = existing_by_id.get(entry_id) if entry_id else None
        if entry_id and entry is None:
            raise HTTPException(400, "One or more leftover fields were not found on this job")
        if entry:
            if entry.status not in FILLABLE_STATUSES:
                raise HTTPException(400, f"{entry.field} is already filled")
            marketplace = marketplace or entry.marketplace
            field = field or entry.field
            selector = selector or (entry.selector or "")
        if not field:
            raise HTTPException(400, "Each field needs a name")
        if not marketplace:
            marketplace = "general"
        if field_lookup_key(field) in SELLER_SETTING_LABELS:
            continue
        if not value:
            value = listing_value_for_field(listing, marketplace, field)
        if marketplace == "poshmark" and field_lookup_key(field) == "category":
            from vendoo_studio.services.registry import map_poshmark_category_path
            mapped = map_poshmark_category_path(listing.get("category_path") or value, listing)
            if mapped:
                value = mapped
        if marketplace == "mercari" and field_lookup_key(field) == "category":
            from vendoo_studio.services.registry import map_mercari_category_path
            mapped = map_mercari_category_path(listing.get("category_path") or value, listing)
            if mapped:
                value = mapped
        if not value:
            continue
        if len(value) > MAX_PATCH_VALUE:
            raise HTTPException(
                400,
                f"Value for {field} is too long ({len(value)} chars; max {MAX_PATCH_VALUE})",
            )
        patch = {
            "marketplace": marketplace,
            "field": field,
            "selector": selector,
            "value": value,
        }
        if entry:
            patch["id"] = entry.id
            patch["entry"] = entry
        else:
            created_specs.append({
                "marketplace": marketplace,
                "field": field,
                "status": "new",
                "reason": "Waiting to fill missing field",
                "selector": selector,
                "value_preview": preview_value(value),
            })
        resolved.append(patch)

    if not resolved:
        raise HTTPException(400, "No values to apply. Ask chat to write the missing values first.")

    if created_specs:
        created = fill_repo.add_entries(
            job_id=job.id,
            conversation_id=job.conversation_id,
            step="filling_fields",
            marketplace=created_specs[0]["marketplace"],
            entries=created_specs,
        )
        created_by_key = {
            (entry.marketplace, normalize_field_label(entry.field)): entry
            for entry in created
        }
        for patch in resolved:
            if patch.get("id"):
                continue
            entry = created_by_key.get((patch["marketplace"], normalize_field_label(patch["field"])))
            if entry:
                patch["id"] = entry.id
                patch["entry"] = entry

    patches = [{
        "id": patch.get("id") or "",
        "marketplace": patch["marketplace"],
        "field": patch["field"],
        "selector": patch.get("selector") or "",
        "value": patch["value"],
    } for patch in resolved]

    snapshot = write_values_into_listing(listing, patches)
    parent_id = revisions[0].id if revisions else job.approved_revision_id
    listing_repo.save_revision(
        conv_id=job.conversation_id,
        listing_json=snapshot,
        source="fill_fields",
        parent_revision_id=parent_id,
    )
    db.refresh(job)

    job.status = "dispatched"
    job.current_step = "filling_fields"
    job.listing_snapshot = {**snapshot, "platforms": (job.listing_snapshot or {}).get("platforms") or []}
    job.last_error = None
    db.commit()

    repo.add_event(
        job_id,
        "fill_fields",
        "filling_fields",
        {"count": len(patches), "patches": patches},
    )
    sent = await dispatch_fill_fields(job, patches)
    if not sent:
        job.status = "failed"
        job.current_step = "filling_fields"
        job.last_error = "Could not reach the Chrome extension"
        db.commit()
        raise HTTPException(503, "Could not reach the Chrome extension")

    for patch in resolved:
        entry = patch.get("entry")
        if entry:
            entry.value_preview = preview_value(patch["value"])
            entry.reason = "Waiting to fill leftover field"
    db.commit()
    db.refresh(job)
    ConversationRepo(db).update_status(job.conversation_id, "listing")
    FillLogService(db).write_markdown(job)
    return _job_response(job)


@router.post("/{job_id}/complete", response_model=JobResponse)
async def resume_completion(job_id: str, db: Session = Depends(get_db)):
    from vendoo_studio.models.job import ACTIVE_JOB_STATUSES
    from vendoo_studio.routes.extension import dispatch_fill_fields, extension_manager
    from vendoo_studio.services.schema_probe import is_schema_probe_job

    repo = JobRepo(db)
    job = repo.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if is_schema_probe_job(job) or job.status == "cancelled" or not job.vendoo_item_id:
        raise HTTPException(400, "Approve a listing for this draft before starting completion.")
    if job.status in ACTIVE_JOB_STATUSES or repo.get_active():
        raise HTTPException(409, "Wait for the current automation job to finish")
    if not extension_manager.connected:
        raise HTTPException(400, "Connect Chrome to verify this draft")
    revisions = ListingRepo(db).get_revisions(job.conversation_id)
    if revisions:
        job.listing_snapshot = {**revisions[0].listing_json, "platforms": (job.listing_snapshot or {}).get("platforms") or []}
    job.status = "dispatched"
    job.current_step = "verifying_draft"
    job.last_error = None
    db.commit()
    repo.add_event(job.id, "completion_resumed", "verifying_draft")
    if not await dispatch_fill_fields(job, []):
        job.status = "failed"
        job.current_step = "completion_blocked"
        job.last_error = "Chrome disconnected before verification"
        db.commit()
        raise HTTPException(503, job.last_error)
    ConversationRepo(db).update_status(job.conversation_id, "listing")
    return _job_response(job)


@router.post("/{job_id}/retry")
async def retry_job(
    job_id: str,
    db: Session = Depends(get_db),
    resume_from: str | None = Query(None),
):
    completion_job = JobRepo(db).get(job_id)
    if completion_job and completion_job.current_step in {"awaiting_answers", "completion_blocked", "resolving_fields", "verifying_draft"}:
        return await resume_completion(job_id, db)
    repo = JobRepo(db)
    job = repo.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status not in {"failed", "dispatched", "completed", "queued", "awaiting_extension"}:
        raise HTTPException(400, f"Job is {job.status}, cannot retry")
    if job.current_step == "filling_fields":
        if job.status == "dispatched":
            raise HTTPException(400, "Leftover field fill is already running")
        raise HTTPException(400, "Retry this leftover fill from Fields")
    if job.status == "cancelled":
        raise HTTPException(400, "Cancelled jobs cannot be retried")

    active = [item for item in JobRepo(db).get_active() if item.id != job.id]
    if active:
        raise HTTPException(409, "Another job is already in progress")

    photo_count = len(ConversationRepo(db).get_photos(job.conversation_id))
    from vendoo_studio.models.validation import validate_listing
    candidate = copy.deepcopy(job.listing_snapshot or {})
    if isinstance(candidate, dict):
        candidate.pop("_schema_probe", None)
    selected = candidate.get("platforms") if isinstance(candidate.get("platforms"), list) else None
    validation = validate_listing(
        candidate,
        photo_count,
        require_photos=True,
        selected_marketplaces=selected,
    )
    requested = str(resume_from or "").strip()
    audit_only = bool(requested) and requested.startswith("auditing_") and requested != "auditing_general"
    if not audit_only and not validation.can_send:
        raise HTTPException(400, _validation_error_detail(validation))

    if requested:
        if not (job.vendoo_item_id or job.vendoo_url):
            raise HTTPException(400, "No Vendoo draft is available yet. Send the listing first.")
        if not requested.startswith("auditing_") or requested == "auditing_general":
            raise HTTPException(400, "Only a marketplace audit step can be retried separately from fill/save")
        resume_from_step = requested
    else:
        resume_from_step = _resume_step_for_retry(job)

    failed_step = job.current_step

    job.status = "queued"
    job.current_step = "queued"
    job.attempt_count += 1
    job.last_error = None

    from vendoo_studio.services.fill_log import FillLogService
    fill_logs = FillLogService(db)
    if resume_from_step:
        fill_logs.clear_step(job_id, resume_from_step)
    else:
        fill_logs.clear_job(job_id)

    db.commit()
    ConversationRepo(db).update_status(job.conversation_id, "listing")
    repo.add_event(job_id, "retried", resume_from_step or "queued", {
        "resume_from": resume_from_step,
        "failed_step": failed_step,
    })

    from vendoo_studio.routes.extension import dispatch_queued_jobs
    await dispatch_queued_jobs()

    return _job_response(job)


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, db: Session = Depends(get_db)):
    repo = JobRepo(db)
    job = repo.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status in {"completed", "cancelled"}:
        raise HTTPException(400, f"Job is already {job.status}")

    job.status = "cancelled"
    job.current_step = None
    db.commit()
    ConversationRepo(db).update_status(job.conversation_id, "draft")
    repo.add_event(job_id, "cancelled")

    from vendoo_studio.models.protocol import ProtocolMessage
    from vendoo_studio.routes.extension import extension_manager
    await extension_manager.send_message(ProtocolMessage(
        type="job.cancel",
        job_id=job_id,
        payload={"job_id": job_id},
    ).model_dump(mode="json"))

    return _job_response(job)


def _generate_sku(listing: dict) -> str:
    brand = str(listing.get("brand") or "").strip()
    size = str(listing.get("size") or "").strip()

    def slug(text: str) -> str:
        chars = [ch.upper() if ch.isalnum() else "-" for ch in text]
        return "-".join(part for part in "".join(chars).split("-") if part)

    parts = []
    if brand:
        parts.append(slug(brand))
    if size:
        parts.append(slug(size))
    return "-".join(parts) if parts else "ITEM"


_NON_RESUMABLE_STEPS = frozenset({
    "",
    "queued",
    "accepted",
    "awaiting_extension",
    "filling_fields",
    "imported",
    "completed",
    "cancelled",
})


def _resume_step_for_retry(job) -> str | None:
    """Return the pipeline step a failed job should resume from, if any."""
    if getattr(job, "status", None) != "failed":
        return None
    step = str(getattr(job, "current_step", None) or "").strip()
    if step in _NON_RESUMABLE_STEPS:
        return None

    has_draft = bool(getattr(job, "vendoo_item_id", None) or getattr(job, "vendoo_url", None))
    general_steps = {
        "opening_vendoo",
        "waiting_ready",
        "uploading_photos",
        "clearing_general",
        "filling_general",
        "saving_general",
        "auditing_general",
    }
    if step in general_steps:
        return step

    marketplace_prefixes = ("clearing_", "filling_", "saving_", "auditing_")
    if step.startswith("auditing_"):
        marketplace = step[len("auditing_") :]
        if marketplace and marketplace != "general":
            return step if has_draft else None
    if step == "discovering_schema" or step.startswith(marketplace_prefixes):
        return step if has_draft else None

    return None


def _validation_error_detail(validation) -> str:
    messages = [err.get("message", "") for err in validation.errors if err.get("message")]
    return "; ".join(messages) or "Listing cannot be sent to Vendoo. Fix validation errors first."


def _prepare_listing_snapshot(
    db: Session,
    conv,
    listing_json: dict,
    *,
    prefer_listing_category: bool = False,
) -> dict:
    from vendoo_studio.services.marketplaces import selected_fillable_platforms
    from vendoo_studio.services.registry import RegistryService, align_listing_gender
    from vendoo_studio.services.vendoo_import import parse_notes

    listing_snapshot = dict(listing_json or {})
    conv_notes = parse_notes(getattr(conv, "notes", None))
    raw_labels = str(conv_notes.get("vendooLabels") or "")
    if raw_labels.strip():
        listing_snapshot["labels"] = [
            label.strip() for label in raw_labels.split(",") if label.strip()
        ]
    listing_category = str(listing_snapshot.get("category_path") or "").strip()
    category_override = str(conv_notes.get("categoryOverride") or "").strip()
    if category_override and (not prefer_listing_category or not listing_category):
        listing_snapshot["category_path"] = category_override
    price_raw = str(conv_notes.get("poshmarkOriginalPrice") or "").strip()
    try:
        poshmark_price = float(price_raw) if price_raw else 0
    except ValueError:
        poshmark_price = 0
    poshmark = listing_snapshot.get("poshmark_specifics") or {}
    if not isinstance(poshmark, dict):
        poshmark = {}
    poshmark["originalPrice"] = poshmark_price
    listing_snapshot["poshmark_specifics"] = poshmark
    align_listing_gender(listing_snapshot)
    _ensure_listing_defaults(listing_snapshot)
    registry = RegistryService(db)
    registry.merge_learned_fields(listing_snapshot)
    for marketplace in selected_fillable_platforms():
        registry.validate_dropdown_fields(
            listing_snapshot, marketplace, listing_snapshot.get("category_path"),
        )
    return listing_snapshot


def _ensure_listing_defaults(listing_snapshot: dict) -> None:
    if not isinstance(listing_snapshot, dict):
        return

    from vendoo_studio.models.schema import ListingSchema

    condition = listing_snapshot.get("condition")
    if condition:
        listing_snapshot["condition"] = ListingSchema.validate_condition(condition)

    if not str(listing_snapshot.get("sku") or "").strip():
        listing_snapshot["sku"] = _generate_sku(listing_snapshot)

    from vendoo_studio.services.registry import map_vendoo_category_path

    mapped_category = map_vendoo_category_path(
        str(listing_snapshot.get("category_path") or ""),
        listing_snapshot,
    )
    if mapped_category:
        listing_snapshot["category_path"] = mapped_category

    mercari = listing_snapshot.get("mercari_specifics") or {}
    if not isinstance(mercari, dict):
        mercari = {}
    label = str(mercari.get("shippingLabel") or "").strip()
    mercari["shippingLabel"] = label or "USPS Ground Advantage"
    listing_snapshot["mercari_specifics"] = mercari

    from vendoo_studio.models.validation import normalize_listing_dropdowns
    normalize_listing_dropdowns(listing_snapshot)


def _job_response(job) -> JobResponse:
    from vendoo_studio.services.schema_probe import is_schema_probe_job

    title = job.listing_snapshot.get("title", "") if job.listing_snapshot else ""
    return JobResponse(
        id=job.id,
        conversation_id=job.conversation_id,
        status=job.status,
        current_step=job.current_step,
        vendoo_item_id=job.vendoo_item_id,
        vendoo_url=job.vendoo_url,
        attempt_count=job.attempt_count,
        last_error=job.last_error,
        listing_title=title,
        mode="schema_probe" if is_schema_probe_job(job) else None,
        created_at=job.created_at.isoformat() if job.created_at else "",
        updated_at=job.updated_at.isoformat() if job.updated_at else "",
    )


@router.get("/{job_id}/photos/{photo_id}")
def serve_job_photo(job_id: str, photo_id: str, db: Session = Depends(get_db)):
    job_repo = JobRepo(db)
    job = job_repo.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    photo = db.query(Photo).filter(
        Photo.id == photo_id,
        Photo.conversation_id == job.conversation_id,
    ).first()
    if not photo:
        raise HTTPException(404, "Photo not found for this job")

    filepath = Path(PHOTOS_DIR) / photo.stored_filename
    if not filepath.exists():
        raise HTTPException(404, "Photo file not found")

    return FileResponse(str(filepath), media_type=photo.mime_type)
