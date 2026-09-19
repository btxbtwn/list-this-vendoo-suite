from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from vendoo_studio.config import PHOTOS_DIR
from vendoo_studio.database import get_db
from vendoo_studio.repositories.queries import (
    BUSY_LISTING_STATUSES,
    ConversationRepo,
    MANUAL_LISTING_STATUSES,
)
from vendoo_studio.models.conversation import Photo as PhotoModel, utcnow

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationCreate(BaseModel):
    title: str | None = None
    notes: str | None = None


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str | None
    notes: str | None
    status: str
    settled_at: str | None = None
    unsettled_at: str | None = None
    created_at: str
    updated_at: str


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    role: str
    text: str
    provider: str | None
    model: str | None
    created_at: str


class PhotoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    original_filename: str
    mime_type: str
    size_bytes: int
    display_order: int
    width: int | None
    height: int | None
    created_at: str
    url: str


@router.post("", response_model=ConversationResponse)
def create_conversation(body: ConversationCreate, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.create(title=body.title, notes=body.notes)
    return _conv_response(conv)


@router.get("", response_model=list[ConversationResponse])
def list_conversations(db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    repo.reconcile_job_statuses()
    return [_conv_response(c) for c in repo.list_all()]


@router.get("/{conv_id}", response_model=ConversationResponse)
def get_conversation(conv_id: str, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return _conv_response(conv)


class ConversationUpdate(BaseModel):
    title: str | None = None
    notes: str | None = None
    status: str | None = None


class DeleteConversationResponse(BaseModel):
    ok: bool
    deleted_jobs: int
    deleted_photos: int


@router.post("/{conv_id}/settle", response_model=ConversationResponse)
def settle_conversation(conv_id: str, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    if conv.status in BUSY_LISTING_STATUSES:
        raise HTTPException(409, "Cannot settle a listing that is still in progress")
    return _conv_response(repo.settle(conv_id))


@router.post("/{conv_id}/unsettle", response_model=ConversationResponse)
def unsettle_conversation(conv_id: str, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return _conv_response(repo.unsettle(conv_id))


class VendooLinkRequest(BaseModel):
    url_or_id: str


class VendooLinkResponse(BaseModel):
    conversation: ConversationResponse
    vendoo_item_id: str
    vendoo_url: str


@router.post("/{conv_id}/vendoo-link", response_model=VendooLinkResponse)
def link_vendoo_draft(conv_id: str, body: VendooLinkRequest, db: Session = Depends(get_db)):
    """Bind this Studio listing to an existing Vendoo draft via URL or item ID."""
    from vendoo_studio.models.job import Job
    from vendoo_studio.services.vendoo_import import merge_notes, parse_vendoo_draft_ref, vendoo_binding

    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    try:
        binding = parse_vendoo_draft_ref(body.url_or_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    item_id = binding["vendooItemId"]
    item_url = binding["vendooUrl"]
    other = repo.find_by_vendoo_item_id(item_id)
    if other and other.id != conv_id:
        title = other.title or "Untitled"
        raise HTTPException(
            409,
            f"That Vendoo draft is already linked to another listing ({title}).",
        )

    conv.notes = merge_notes(conv.notes, binding)
    conv.updated_at = utcnow()

    # Keep any existing jobs pointed at the same draft so Fields can refresh.
    jobs = (
        db.query(Job)
        .filter(Job.conversation_id == conv_id, Job.status != "cancelled")
        .all()
    )
    for job in jobs:
        job.vendoo_item_id = item_id
        job.vendoo_url = item_url

    db.commit()
    db.refresh(conv)
    linked = vendoo_binding(conv.notes)
    return VendooLinkResponse(
        conversation=_conv_response(conv),
        vendoo_item_id=linked.get("vendooItemId") or item_id,
        vendoo_url=linked.get("vendooUrl") or item_url,
    )


@router.patch("/{conv_id}")
def update_conversation(conv_id: str, body: ConversationUpdate, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    changed = False
    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise HTTPException(400, "Title cannot be empty")
        if title != (conv.title or ""):
            conv.title = title
            conv.updated_at = utcnow()
            changed = True
    if body.notes is not None:
        from vendoo_studio.services.vendoo_import import merge_notes, parse_notes
        incoming = parse_notes(body.notes)
        if incoming:
            conv.notes = merge_notes(conv.notes, incoming)
        else:
            conv.notes = body.notes
        changed = True
    if body.status is not None:
        status = body.status.strip().lower().replace(" ", "_").replace("-", "_")
        if status not in MANUAL_LISTING_STATUSES:
            raise HTTPException(
                400,
                f"Status must be one of: {', '.join(MANUAL_LISTING_STATUSES)}",
            )
        if status != conv.status:
            # Commit title/notes first so update_status's own commit stays consistent.
            if changed:
                db.commit()
                db.refresh(conv)
                changed = False
            conv = repo.update_status(conv_id, status, touch_updated_at=True)
            return _conv_response(conv)
    if changed:
        db.commit()
        db.refresh(conv)
    return _conv_response(conv)


@router.get("/{conv_id}/messages")
def get_messages(conv_id: str, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    msgs = repo.get_messages(conv_id)
    return [_msg_response(m) for m in msgs]


@router.get("/{conv_id}/photos")
def get_photos(conv_id: str, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    return [_photo_response(p) for p in repo.get_photos(conv_id)]


def _wipe_conversation_contents(
    db: Session, conv_id: str, *, keep_photos: bool = False
) -> tuple[int, int]:
    import os as _os

    repo = ConversationRepo(db)
    photos = [] if keep_photos else repo.get_photos(conv_id)
    deleted_photos = len(photos)
    for photo in photos:
        filepath = Path(PHOTOS_DIR) / photo.stored_filename
        if filepath.exists():
            _os.remove(filepath)

    from vendoo_studio.models.diagnostics import DiagnosticRun, FieldObservation
    from vendoo_studio.models.fill_log import FillLogEntry
    from vendoo_studio.models.job import Job, JobEvent
    from vendoo_studio.models.listing import Listing, ListingRevision
    from vendoo_studio.models.conversation import Message

    job_ids = [row[0] for row in db.query(Job.id).filter(Job.conversation_id == conv_id).all()]
    if job_ids:
        db.query(FieldObservation).filter(
            FieldObservation.diagnostic_run_id.in_(
                db.query(DiagnosticRun.id).filter(DiagnosticRun.job_id.in_(job_ids))
            )
        ).delete(synchronize_session=False)
        db.query(DiagnosticRun).filter(DiagnosticRun.job_id.in_(job_ids)).delete(synchronize_session=False)
        db.query(FillLogEntry).filter(FillLogEntry.job_id.in_(job_ids)).delete(synchronize_session=False)
        db.query(JobEvent).filter(JobEvent.job_id.in_(job_ids)).delete(synchronize_session=False)
        db.query(Job).filter(Job.conversation_id == conv_id).delete(synchronize_session=False)

    db.query(ListingRevision).filter(ListingRevision.conversation_id == conv_id).delete(synchronize_session=False)
    db.query(Listing).filter(Listing.conversation_id == conv_id).delete(synchronize_session=False)
    db.query(Message).filter(Message.conversation_id == conv_id).delete(synchronize_session=False)
    if not keep_photos:
        db.query(PhotoModel).filter(PhotoModel.conversation_id == conv_id).delete(synchronize_session=False)
    return len(job_ids), deleted_photos


@router.delete("/{conv_id}/photos/{photo_id}")
def delete_photo(conv_id: str, photo_id: str, db: Session = Depends(get_db)):
    import os

    repo = ConversationRepo(db)
    photos = repo.get_photos(conv_id)
    target = next((p for p in photos if p.id == photo_id), None)
    if not target:
        raise HTTPException(404, "Photo not found")

    filepath = Path(PHOTOS_DIR) / target.stored_filename
    if filepath.exists():
        os.remove(filepath)

    repo.delete_photo(conv_id, photo_id)
    return {"ok": True}


class ResetRequest(BaseModel):
    # Regenerate: drop chat, jobs and generated fields but keep photos and item
    # details, so the next generate starts from the same inputs as a new listing.
    keep_inputs: bool = False


@router.post("/{conv_id}/reset", response_model=ConversationResponse)
async def reset_conversation(
    conv_id: str, body: ResetRequest | None = None, db: Session = Depends(get_db)
):
    keep_inputs = bool(body and body.keep_inputs)
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    from vendoo_studio.models.job import ACTIVE_JOB_STATUSES, Job
    from vendoo_studio.models.protocol import ProtocolMessage
    from vendoo_studio.repositories.queries import ListingRepo
    from vendoo_studio.services.streaming import stop_generation
    from vendoo_studio.routes.extension import extension_manager
    from vendoo_studio.services.hidden_fields import clear_listing_hidden_fields
    from vendoo_studio.services.vendoo_import import merge_notes, vendoo_binding

    stop_generation(conv_id, discard=True)

    # Keep the Vendoo draft link across Clear; wipe only Studio form contents.
    binding = vendoo_binding(conv.notes)
    notes = conv.notes

    active_jobs = db.query(Job).filter(
        Job.conversation_id == conv_id,
        Job.status.in_(ACTIVE_JOB_STATUSES),
    ).all()
    for job in active_jobs:
        job.status = "cancelled"
        job.current_step = None
        await extension_manager.send_message(ProtocolMessage(
            type="job.cancel",
            job_id=job.id,
            payload={"job_id": job.id},
        ).model_dump(mode="json"))

    _wipe_conversation_contents(db, conv_id, keep_photos=keep_inputs)
    db.expire_all()
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    conv.title = "New Listing"
    if keep_inputs:
        conv.notes = notes
    else:
        conv.notes = merge_notes(None, binding) if binding else None
    conv.status = "draft"
    conv.settled_at = None
    conv.unsettled_at = None
    conv.updated_at = utcnow()
    if binding:
        # Blank revision so Fields / ensure-draft can reattach to the same Vendoo item.
        ListingRepo(db).save_revision(conv_id, {}, source="reset")
    db.commit()
    db.refresh(conv)
    clear_listing_hidden_fields(conv_id)
    return _conv_response(conv)


@router.delete("/{conv_id}", response_model=DeleteConversationResponse)
def delete_conversation(conv_id: str, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    from vendoo_studio.models.job import ACTIVE_JOB_STATUSES, Job

    active_jobs = db.query(Job).filter(
        Job.conversation_id == conv_id,
        Job.status.in_(ACTIVE_JOB_STATUSES),
    ).all()
    if active_jobs:
        raise HTTPException(400, "Cannot delete a listing with an active automation job")

    deleted_jobs, deleted_photos = _wipe_conversation_contents(db, conv_id)
    db.expire_all()
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    db.delete(conv)
    db.commit()
    return DeleteConversationResponse(ok=True, deleted_jobs=deleted_jobs, deleted_photos=deleted_photos)


def _msg_response(msg) -> dict:
    return {
        "id": msg.id,
        "conversation_id": msg.conversation_id,
        "role": msg.role,
        "text": msg.text,
        "provider": msg.provider,
        "model": msg.model,
        "created_at": msg.created_at.isoformat() if msg.created_at else "",
    }


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _conv_response(conv) -> ConversationResponse:
    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        notes=conv.notes,
        status=conv.status,
        settled_at=_iso(conv.settled_at),
        unsettled_at=_iso(conv.unsettled_at),
        created_at=conv.created_at.isoformat() if conv.created_at else "",
        updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
    )


def _photo_response(photo) -> PhotoResponse:
    return PhotoResponse(
        id=photo.id,
        conversation_id=photo.conversation_id,
        original_filename=photo.original_filename,
        mime_type=photo.mime_type,
        size_bytes=photo.size_bytes,
        display_order=photo.display_order,
        width=photo.width,
        height=photo.height,
        created_at=photo.created_at.isoformat() if photo.created_at else "",
        url=f"/api/photos/{photo.id}",
    )
