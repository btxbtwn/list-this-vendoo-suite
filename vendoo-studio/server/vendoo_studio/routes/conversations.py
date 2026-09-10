from __future__ import annotations

from typing import Optional
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vendoo_studio.config import PHOTOS_DIR
from vendoo_studio.database import get_db
from vendoo_studio.repositories.queries import ConversationRepo
from vendoo_studio.models.conversation import Photo as PhotoModel

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationCreate(BaseModel):
    title: Optional[str] = None
    notes: Optional[str] = None


class ConversationResponse(BaseModel):
    id: str
    title: Optional[str]
    notes: Optional[str]
    status: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    role: str
    text: str
    provider: Optional[str]
    model: Optional[str]
    created_at: str

    class Config:
        from_attributes = True


class PhotoResponse(BaseModel):
    id: str
    conversation_id: str
    original_filename: str
    mime_type: str
    size_bytes: int
    display_order: int
    width: Optional[int]
    height: Optional[int]
    created_at: str
    url: str

    class Config:
        from_attributes = True


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
    notes: Optional[str] = None


class DeleteConversationResponse(BaseModel):
    ok: bool
    deleted_jobs: int
    deleted_photos: int


@router.patch("/{conv_id}")
def update_conversation(conv_id: str, body: ConversationUpdate, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    if body.notes is not None:
        conv.notes = body.notes
        db.commit()
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


@router.delete("/{conv_id}", response_model=DeleteConversationResponse)
def delete_conversation(conv_id: str, db: Session = Depends(get_db)):
    import os as _os

    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    from vendoo_studio.models.job import ACTIVE_JOB_STATUSES, Job, JobEvent
    from vendoo_studio.models.diagnostics import DiagnosticRun, FieldObservation
    from vendoo_studio.models.fill_log import FillLogEntry

    active_jobs = db.query(Job).filter(
        Job.conversation_id == conv_id,
        Job.status.in_(ACTIVE_JOB_STATUSES),
    ).all()
    if active_jobs:
        raise HTTPException(400, "Cannot delete a listing with an active automation job")

    photos = repo.get_photos(conv_id)
    deleted_photos = len(photos)
    for p in photos:
        filepath = Path(PHOTOS_DIR) / p.stored_filename
        if filepath.exists():
            _os.remove(filepath)

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
    deleted_jobs = len(job_ids)

    from vendoo_studio.models.listing import Listing, ListingRevision
    from vendoo_studio.models.conversation import Message

    db.query(ListingRevision).filter(ListingRevision.conversation_id == conv_id).delete(synchronize_session=False)
    db.query(Listing).filter(Listing.conversation_id == conv_id).delete(synchronize_session=False)
    db.query(Message).filter(Message.conversation_id == conv_id).delete(synchronize_session=False)
    db.query(PhotoModel).filter(PhotoModel.conversation_id == conv_id).delete(synchronize_session=False)

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


def _conv_response(conv) -> ConversationResponse:
    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        notes=conv.notes,
        status=conv.status,
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
