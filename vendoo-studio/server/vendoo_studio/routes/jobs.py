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
from vendoo_studio.repositories.queries import JobRepo, ConversationRepo, ListingRepo
from vendoo_studio.config import PHOTOS_DIR
from vendoo_studio.models.conversation import Photo
from vendoo_studio.services.job_snapshot import (
    blocker_fields_for_job,
    prepare_listing_snapshot,
    resume_step_for_retry,
    validation_error_detail,
)

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
    # Marketplace/field gaps from the latest completion pause (Ask chat targets).
    blocker_fields: list[dict] | None = None
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
    listing_snapshot = prepare_listing_snapshot(db, conv, latest_revision.listing_json)
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
        raise HTTPException(400, validation_error_detail(validation))

    existing_item_id = str(binding.get("vendooItemId") or "").strip()
    if existing_item_id and existing_item_id.lower() != "new" and not body.confirm_overwrite:
        raise HTTPException(
            409,
            "This listing is already bound to a Vendoo draft. Confirm overwrite to update that draft.",
        )

    from vendoo_studio.models.job import ACTIVE_JOB_STATUSES
    from vendoo_studio.services.schema_probe import is_schema_probe_job

    job_repo = JobRepo(db)
    for prior in job_repo.list_by_conversation(body.conversation_id):
        if prior.status in ACTIVE_JOB_STATUSES and not is_schema_probe_job(prior):
            raise HTTPException(
                409,
                "This listing is already queued or sending to Vendoo",
            )

    approved_revision = listing_repo.save_revision(
        conv_id=body.conversation_id,
        listing_json=listing_snapshot,
        source="normalized",
        parent_revision_id=latest_revision.id,
    )
    conv_repo.update_status(body.conversation_id, "listing")

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


class EnsureDraftJobRequest(BaseModel):
    conversation_id: str


@router.post("/ensure-draft", response_model=JobResponse)
def ensure_draft_job(body: EnsureDraftJobRequest, db: Session = Depends(get_db)):
    """Attach Fields to an existing Vendoo draft binding without starting a Send."""
    from vendoo_studio.services.vendoo_import import vendoo_binding
    from vendoo_studio.services.schema_probe import is_schema_probe_job

    conv_repo = ConversationRepo(db)
    conv = conv_repo.get(body.conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    binding = vendoo_binding(conv.notes)
    item_id = str(binding.get("vendooItemId") or "").strip()
    item_url = str(binding.get("vendooUrl") or "").strip()
    if not item_id or item_id.lower() in {"new", "edit", "create"}:
        raise HTTPException(400, "No Vendoo draft is bound to this listing yet.")
    if not item_url:
        item_url = f"https://web.vendoo.co/app/item/{item_id}"

    job_repo = JobRepo(db)
    for prior in job_repo.list_by_conversation(body.conversation_id):
        if prior.status == "cancelled":
            continue
        if prior.vendoo_item_id == item_id or (not prior.vendoo_item_id and not is_schema_probe_job(prior)):
            if not prior.vendoo_item_id or not prior.vendoo_url:
                prior.vendoo_item_id = prior.vendoo_item_id or item_id
                prior.vendoo_url = prior.vendoo_url or item_url
                db.commit()
                db.refresh(prior)
            return _job_response(prior)

    listing_repo = ListingRepo(db)
    revisions = listing_repo.get_revisions(body.conversation_id)
    if not revisions:
        # A blank listing can still attach; linking imports the draft's fields next.
        listing_repo.save_revision(body.conversation_id, {}, source="vendoo_link")
        revisions = listing_repo.get_revisions(body.conversation_id)
    snapshot = dict(revisions[0].listing_json or {})
    job = job_repo.create(
        conv_id=body.conversation_id,
        approved_revision_id=revisions[0].id,
        listing_snapshot=snapshot,
        vendoo_item_id=item_id,
        vendoo_url=item_url,
        status="completed",
        current_step="fields_applied",
    )
    job_repo.add_event(job.id, "ensured_draft", "fields_applied", {
        "vendoo_item_id": item_id,
        "vendoo_url": item_url,
    })
    return _job_response(job)


@router.get("", response_model=list[JobResponse])
def list_jobs(conversation_id: str | None = None, db: Session = Depends(get_db)):
    repo = JobRepo(db)
    if conversation_id:
        conv = ConversationRepo(db).get(conversation_id)
        if not conv:
            raise HTTPException(404, "Conversation not found")
        return [_job_response(j) for j in repo.list_by_conversation(conversation_id)]
    return [_job_response(j) for j in repo.list_all()]


@router.get("/fill-stats")
def get_fill_stats(days: int = Query(30, ge=1, le=365), limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    from vendoo_studio.services.job_metrics import fill_success_stats

    return fill_success_stats(db, days=days, limit=limit)


@router.get("/{job_id}/timing")
def get_job_timing(job_id: str, db: Session = Depends(get_db)):
    from vendoo_studio.services.job_metrics import job_timing

    if not JobRepo(db).get(job_id):
        raise HTTPException(404, "Job not found")
    return job_timing(db, job_id)


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
                except TimeoutError:
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
    resolve_photos: bool = False,
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

    # Fields live scrape shares the Vendoo tab with Send/verify. Serving cache (or a busy
    # error) prevents Discovering… from fighting marketplace form mounting mid-verification.
    from vendoo_studio.services.completion_readback import AUTOMATION_TAB_STEPS

    if job.status == "dispatched" and str(job.current_step or "") in AUTOMATION_TAB_STEPS:
        if cached:
            return VendooItemResponse(
                ok=True,
                source=cached.get("source") or "cache",
                item_id=cached.get("item_id") or job.vendoo_item_id,
                url=cached.get("url") or job.vendoo_url,
                error=None,
                api_error="Draft refresh paused while automation uses the Vendoo tab",
                item=cached.get("item"),
                form=cached.get("form"),
                statuses=cached.get("statuses"),
            )
        raise HTTPException(
            409,
            "Draft refresh is paused while verification or fill is using the Vendoo tab",
        )

    request_id = uuid.uuid4().hex[:12]
    waiter = extension_manager.register_wait(request_id)
    try:
        sent = await dispatch_vendoo_get(job, request_id, resolve_photos=resolve_photos)
        if not sent:
            raise HTTPException(503, "Could not reach the Chrome extension")
        try:
            payload = await asyncio.wait_for(waiter, timeout=VENDOO_GET_TIMEOUT_SEC)
        except TimeoutError:
            raise HTTPException(
                504,
                "Chrome did not return the Vendoo draft in time. Open the listing tab and try again.",
            ) from None
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


class ImportDraftResponse(BaseModel):
    ok: bool
    listing_title: str
    photo_count: int
    photo_warnings: list[str] = []


@router.post("/{job_id}/import-draft", response_model=ImportDraftResponse)
async def import_draft(job_id: str, db: Session = Depends(get_db)):
    """Copy the last-read Vendoo draft into the Studio listing and pull its photos."""
    from vendoo_studio.services.vendoo_import import import_vendoo_draft

    repo = JobRepo(db)
    job = repo.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    cached = repo.get_vendoo_draft(job_id)
    if not cached:
        raise HTTPException(400, "Read the Vendoo draft before importing it.")

    result = await import_vendoo_draft(db, job.conversation_id, cached.get("item"), cached.get("form"))
    job.approved_revision_id = result["revision"].id
    job.listing_snapshot = result["listing"]
    db.commit()
    ConversationRepo(db).add_message(
        job.conversation_id,
        "system",
        f"Imported fields from linked Vendoo item {job.vendoo_item_id}.",
    )
    return ImportDraftResponse(
        ok=True,
        listing_title=str(result["listing"].get("title") or ""),
        photo_count=result["photo_count"],
        photo_warnings=result["photo_warnings"],
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
    body: ResolveCategoryRequest | None = None,
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
    from vendoo_studio.services.fill_fields import FillFieldsError, plan_fill_fields
    from vendoo_studio.services.fill_log import FillLogService, preview_value, write_values_into_listing

    repo = JobRepo(db)
    job = repo.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status in ACTIVE_JOB_STATUSES:
        raise HTTPException(400, "Wait for the current fill to finish")
    # Leftover fill must not jump ahead of waiting Send approvals.
    active = [item for item in JobRepo(db).get_active() if item.id != job.id]
    if active:
        raise HTTPException(409, "Another job is already queued or in progress")
    if job.status not in {"completed", "failed"}:
        raise HTTPException(400, f"Job is {job.status}, cannot fill leftover fields")
    if not job.vendoo_url and not job.vendoo_item_id:
        raise HTTPException(400, "No Vendoo draft is available yet. Send the listing first.")
    if not extension_manager.connected:
        raise HTTPException(400, "Chrome is not connected")

    try:
        plan = plan_fill_fields(db, job, body.fields)
    except FillFieldsError as exc:
        raise HTTPException(400, str(exc)) from exc
    patches = plan.patches

    snapshot = write_values_into_listing(plan.listing, patches)
    parent_id = plan.revisions[0].id if plan.revisions else job.approved_revision_id
    ListingRepo(db).save_revision(
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
    sent = await dispatch_fill_fields(job, patches, verify=False)
    if not sent:
        job.status = "failed"
        job.current_step = "filling_fields"
        job.last_error = "Could not reach the Chrome extension"
        db.commit()
        raise HTTPException(503, "Could not reach the Chrome extension")

    for patch in plan.resolved:
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
    if job.status in ACTIVE_JOB_STATUSES or [j for j in repo.get_active() if j.id != job.id]:
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

    # Rejoin the FIFO behind any already-waiting approvals (do not jump the queue).
    from vendoo_studio.models.conversation import utcnow

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
        raise HTTPException(400, validation_error_detail(validation))

    if requested:
        if not (job.vendoo_item_id or job.vendoo_url):
            raise HTTPException(400, "No Vendoo draft is available yet. Send the listing first.")
        if not requested.startswith("auditing_") or requested == "auditing_general":
            raise HTTPException(400, "Only a marketplace audit step can be retried separately from fill/save")
        resume_from_step = requested
    else:
        resume_from_step = resume_step_for_retry(job)

    failed_step = job.current_step

    job.status = "queued"
    job.current_step = "queued"
    job.attempt_count += 1
    job.last_error = None
    job.created_at = utcnow()

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
    from vendoo_studio.routes.extension import dispatch_queued_jobs, extension_manager
    await extension_manager.send_message(ProtocolMessage(
        type="job.cancel",
        job_id=job_id,
        payload={"job_id": job_id},
    ).model_dump(mode="json"))
    await dispatch_queued_jobs()

    return _job_response(job)


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
        blocker_fields=blocker_fields_for_job(job),
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


class VendooCreateResponse(BaseModel):
    ok: bool
    item_id: str
    url: str
    unresolved: list[dict] = []
    diff: list[dict] = []


class VendooProbeRequest(BaseModel):
    item_ids: list[str] = Field(default_factory=list, max_length=50)


class VendooProbeResponse(BaseModel):
    ok: bool
    learned_from: int
    item_count: int
    fields: list[str]
    failures: list[dict] = []


def _vendoo_error(exc: Exception) -> HTTPException:
    from vendoo_studio.services.browser_bridge import BrowserBridgeError
    from vendoo_studio.services.vendoo_create import VendooCreateError

    if isinstance(exc, BrowserBridgeError):
        return HTTPException(400, str(exc))
    if isinstance(exc, VendooCreateError):
        return HTTPException(502, str(exc))
    return HTTPException(500, str(exc))


@router.post("/{job_id}/vendoo-api/probe", response_model=VendooProbeResponse)
async def vendoo_api_probe(job_id: str, body: VendooProbeRequest, db: Session = Depends(get_db)):
    """Learn Vendoo's condition/colour/category encodings from the user's own items.

    With no ids given, every Vendoo item Studio already knows about is read.
    """
    from vendoo_studio.services.vendoo_create import probe_schema
    from vendoo_studio.services.vendoo_import import vendoo_binding

    job = JobRepo(db).get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    item_ids = list(body.item_ids)
    if not item_ids:
        for conv in ConversationRepo(db).list_all():
            bound = vendoo_binding(conv.notes).get("vendooItemId")
            if bound:
                item_ids.append(bound)
        for other in JobRepo(db).list_all():
            if other.vendoo_item_id and other.vendoo_item_id not in item_ids:
                item_ids.append(other.vendoo_item_id)
    if not item_ids:
        raise HTTPException(400, "No Vendoo items to learn from yet. Paste an item id or import a draft first.")
    try:
        out = await probe_schema(job, item_ids[:50])
    except Exception as exc:  # noqa: BLE001 - surfaced as HTTP
        raise _vendoo_error(exc) from exc
    schema = out["schema"]
    return VendooProbeResponse(
        ok=True,
        learned_from=out["learned_from"],
        item_count=int(schema.get("item_count") or 0),
        fields=sorted((schema.get("fields") or {}).keys()),
        failures=out["failures"],
    )


@router.post("/{job_id}/vendoo-api/create", response_model=VendooCreateResponse)
async def vendoo_api_create(job_id: str, db: Session = Depends(get_db)):
    """Create the job's listing in Vendoo through Vendoo's own item API — no form filling."""
    from vendoo_studio.services.vendoo_create import create_item
    from vendoo_studio.services.vendoo_import import merge_notes

    repo = JobRepo(db)
    job = repo.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.vendoo_item_id:
        raise HTTPException(409, f"This job already has Vendoo item {job.vendoo_item_id}")
    listing = job.listing_snapshot if isinstance(job.listing_snapshot, dict) else {}
    conv_repo = ConversationRepo(db)
    photos = conv_repo.get_photos(job.conversation_id)
    try:
        out = await create_item(job, listing, photos)
    except Exception as exc:  # noqa: BLE001 - surfaced as HTTP
        repo.add_event(job.id, "vendoo_api_create_failed", None, {"error": str(exc)})
        raise _vendoo_error(exc) from exc

    job.vendoo_item_id = out["item_id"]
    job.vendoo_url = out["url"]
    conv = conv_repo.get(job.conversation_id)
    if conv:
        conv.notes = merge_notes(conv.notes, {"vendooItemId": out["item_id"], "vendooUrl": out["url"]})
    db.commit()
    repo.add_event(job.id, "vendoo_api_created", None, {
        "item_id": out["item_id"],
        "unresolved": out["unresolved"],
        "diff": out["diff"],
    })
    if out.get("stored"):
        repo.save_vendoo_draft(job.id, item=out["stored"], item_id=out["item_id"], url=out["url"], source="api")
    return VendooCreateResponse(ok=True, item_id=out["item_id"], url=out["url"], unresolved=out["unresolved"], diff=out["diff"])
