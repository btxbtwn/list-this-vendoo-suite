from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from pathlib import Path

from vendoo_studio.database import get_db
from vendoo_studio.repositories.queries import JobRepo, ConversationRepo, ListingRepo
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
    created_at: str
    updated_at: str


class CreateJobRequest(BaseModel):
    conversation_id: str


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

    listing_snapshot = dict(latest_revision.listing_json)

    import json as _json
    try:
        conv_notes = _json.loads(conv.notes or "{}")
        raw_labels = conv_notes.get("vendooLabels", "")
        if raw_labels:
            listing_snapshot["labels"] = [
                label.strip() for label in str(raw_labels).split(",") if label.strip()
            ]
        category_override = conv_notes.get("categoryOverride", "").strip()
        if category_override:
            listing_snapshot["category_path"] = category_override
        poshmark_price_override = conv_notes.get("poshmarkOriginalPrice", "").strip()
        if poshmark_price_override:
            try:
                poshmark_price = float(poshmark_price_override)
            except ValueError:
                poshmark_price = 0
        else:
            poshmark_price = 0
    except Exception:
        poshmark_price = 0

    poshmark = listing_snapshot.get("poshmark_specifics") or {}
    if isinstance(poshmark, dict):
        poshmark["originalPrice"] = poshmark_price
    listing_snapshot["poshmark_specifics"] = poshmark

    _ensure_listing_defaults(listing_snapshot)

    from vendoo_studio.services.registry import RegistryService
    registry = RegistryService(db)
    all_warnings = []
    for marketplace in ("ebay", "etsy", "poshmark", "mercari", "depop"):
        mp_warnings = registry.validate_dropdown_fields(
            listing_snapshot, marketplace, listing_snapshot.get("category_path"),
        )
        all_warnings.extend(mp_warnings)

    from vendoo_studio.models.validation import validate_listing
    validation = validate_listing(listing_snapshot, photo_count)
    if not validation.can_send:
        raise HTTPException(400, {
            "message": "Listing cannot be sent to Vendoo. Fix validation errors first.",
            "errors": validation.errors,
            "warnings": validation.warnings,
        })

    active = JobRepo(db).get_active()
    if active:
        raise HTTPException(409, "Another job is already in progress")

    listing_repo.save_revision(
        conv_id=body.conversation_id,
        listing_json=listing_snapshot,
        source="normalized",
        parent_revision_id=latest_revision.id,
    )
    conv_repo.update_status(body.conversation_id, "listing")

    job_repo = JobRepo(db)
    job = job_repo.create(
        conv_id=body.conversation_id,
        approved_revision_id=latest_revision.id,
        listing_snapshot=listing_snapshot,
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


@router.post("/{job_id}/retry")
async def retry_job(job_id: str, db: Session = Depends(get_db)):
    repo = JobRepo(db)
    job = repo.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status not in {"failed", "dispatched", "completed"}:
        raise HTTPException(400, f"Job is {job.status}, can only retry failed or dispatched jobs")

    job.status = "queued"
    job.current_step = "queued"
    job.attempt_count += 1
    job.last_error = None

    from vendoo_studio.services.fill_log import FillLogService
    FillLogService(db).clear_job(job_id)

    import json as _json
    try:
        from vendoo_studio.repositories.queries import ConversationRepo
        conv = ConversationRepo(db).get(job.conversation_id)
        if conv:
            conv_notes = _json.loads(conv.notes or "{}")
            raw_labels = conv_notes.get("vendooLabels", "")
            if raw_labels and isinstance(job.listing_snapshot, dict):
                job.listing_snapshot["labels"] = [
                    label.strip() for label in str(raw_labels).split(",") if label.strip()
                ]
            if isinstance(job.listing_snapshot, dict):
                poshmark = job.listing_snapshot.get("poshmark_specifics") or {}
                if isinstance(poshmark, dict):
                    poshmark["originalPrice"] = 0
                job.listing_snapshot["poshmark_specifics"] = poshmark

                category_override = conv_notes.get("categoryOverride", "").strip()
                if category_override:
                    job.listing_snapshot["category_path"] = category_override
    except Exception:
        pass

    if isinstance(job.listing_snapshot, dict):
        _ensure_listing_defaults(job.listing_snapshot)
        from vendoo_studio.services.registry import RegistryService
        registry = RegistryService(db)
        category_path = job.listing_snapshot.get("category_path", "")
        for marketplace in ("ebay", "etsy", "poshmark", "mercari", "depop"):
            registry.validate_dropdown_fields(
                job.listing_snapshot, marketplace, category_path,
            )

    db.commit()
    ConversationRepo(db).update_status(job.conversation_id, "listing")
    repo.add_event(job_id, "retried", job.current_step)

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
    ).model_dump())

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


def _ensure_listing_defaults(listing_snapshot: dict) -> None:
    if not isinstance(listing_snapshot, dict):
        return

    from vendoo_studio.models.schema import ListingSchema

    condition = listing_snapshot.get("condition")
    if condition:
        listing_snapshot["condition"] = ListingSchema.validate_condition(condition)

    if not str(listing_snapshot.get("sku") or "").strip():
        listing_snapshot["sku"] = _generate_sku(listing_snapshot)

    mercari = listing_snapshot.get("mercari_specifics") or {}
    if not isinstance(mercari, dict):
        mercari = {}
    label = str(mercari.get("shippingLabel") or "").strip()
    mercari["shippingLabel"] = label or "USPS Ground Advantage"
    listing_snapshot["mercari_specifics"] = mercari


def _job_response(job) -> JobResponse:
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
