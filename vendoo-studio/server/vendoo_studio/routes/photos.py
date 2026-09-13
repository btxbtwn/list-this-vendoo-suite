from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.repositories.queries import ConversationRepo
from vendoo_studio.services.photos import process_upload, stored_photo_path

router = APIRouter(tags=["photos"])


@router.post("/api/conversations/{conv_id}/photos")
async def upload_photos(
    conv_id: str,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    existing = repo.get_photos(conv_id)
    if len(existing) + len(files) > 20:
        raise HTTPException(400, "Maximum 20 photos per listing")

    results = []
    for f in files:
        try:
            meta = await process_upload(conv_id, f)
        except ValueError as e:
            raise HTTPException(400, str(e))

        try:
            photo = repo.add_photo(
                conv_id=conv_id,
                original_filename=meta["original_filename"],
                stored_filename=meta["stored_filename"],
                mime_type=meta["mime_type"],
                size_bytes=meta["size_bytes"],
                checksum=meta["checksum"],
                width=meta["width"],
                height=meta["height"],
            )
        except Exception:
            filepath = stored_photo_path(meta["stored_filename"])
            if filepath.exists():
                os.remove(filepath)
            raise HTTPException(500, "Failed to persist photo record")

        results.append({
            "id": photo.id,
            "conversation_id": photo.conversation_id,
            "original_filename": photo.original_filename,
            "mime_type": photo.mime_type,
            "size_bytes": photo.size_bytes,
            "display_order": photo.display_order,
            "width": photo.width,
            "height": photo.height,
            "created_at": photo.created_at.isoformat() if photo.created_at else "",
            "url": f"/api/photos/{photo.id}",
        })

    return {"ok": True, "count": len(results), "photos": results}


@router.patch("/api/conversations/{conv_id}/photos/order")
def reorder_photos(conv_id: str, ordered_ids: list[str], db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    repo.reorder_photos(conv_id, ordered_ids)
    return {"ok": True}


@router.get("/api/photos/{photo_id}")
def serve_photo(photo_id: str, db: Session = Depends(get_db)):
    from fastapi.responses import FileResponse
    from vendoo_studio.models.conversation import Photo

    photo = db.query(Photo).filter(Photo.id == photo_id).first()
    if not photo:
        raise HTTPException(404, "Photo not found")

    try:
        filepath = stored_photo_path(photo.stored_filename)
    except ValueError:
        raise HTTPException(404, "Photo file not found")
    if not filepath.exists():
        raise HTTPException(404, "Photo file not found")

    return FileResponse(str(filepath), media_type=photo.mime_type)
