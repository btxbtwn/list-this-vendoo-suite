from __future__ import annotations

from typing import Optional
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vendoo_studio.config import PHOTOS_DIR
from vendoo_studio.database import get_db
from vendoo_studio.repositories.queries import ConversationRepo

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
