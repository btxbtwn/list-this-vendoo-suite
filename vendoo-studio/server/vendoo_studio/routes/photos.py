from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.config import PHOTOS_DIR
from vendoo_studio.repositories.queries import ConversationRepo
from vendoo_studio.services.photos import (
    THUMBNAIL_MIME,
    THUMBNAIL_SIZES,
    get_or_create_thumbnail,
    process_upload,
)

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
    failures: list[str] = []
    for f in files:
        try:
            meta = await process_upload(conv_id, f)
        except ValueError as e:
            failures.append(f"{f.filename or 'file'}: {e}")
            continue

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
            filepath = Path(PHOTOS_DIR) / meta["stored_filename"]
            if filepath.exists():
                os.remove(filepath)
            failures.append(f"{f.filename or 'file'}: Failed to persist photo record")
            continue

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

    if failures and not results:
        raise HTTPException(400, failures[0] if len(failures) == 1 else "Some photos could not be uploaded: " + "; ".join(failures))
    if failures:
        return {
            "ok": True,
            "count": len(results),
            "photos": results,
            "errors": failures,
            "message": f"Saved {len(results)} photo(s). {len(failures)} file(s) failed: " + "; ".join(failures),
        }

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

    filepath = Path(PHOTOS_DIR) / photo.stored_filename
    if not filepath.exists():
        raise HTTPException(404, "Photo file not found")

    return FileResponse(str(filepath), media_type=photo.mime_type)


@router.get("/api/photos/{photo_id}/thumb")
def serve_photo_thumbnail(photo_id: str, size: int = 96, db: Session = Depends(get_db)):
    from fastapi.responses import FileResponse
    from vendoo_studio.models.conversation import Photo

    if size not in THUMBNAIL_SIZES:
        raise HTTPException(400, f"Unsupported thumbnail size: {size}")

    photo = db.query(Photo).filter(Photo.id == photo_id).first()
    if not photo:
        raise HTTPException(404, "Photo not found")

    try:
        thumb = get_or_create_thumbnail(photo.stored_filename, size)
    except FileNotFoundError:
        raise HTTPException(404, "Photo file not found") from None
    except Exception:
        # HEIC and other formats Pillow cannot decode fall back to the original.
        filepath = Path(PHOTOS_DIR) / photo.stored_filename
        if not filepath.exists():
            raise HTTPException(404, "Photo file not found") from None
        return FileResponse(str(filepath), media_type=photo.mime_type)

    return FileResponse(
        str(thumb),
        media_type=THUMBNAIL_MIME,
        headers={"Cache-Control": "private, max-age=86400"},
    )
