from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from fastapi import UploadFile
from PIL import Image

from vendoo_studio.config import PHOTOS_DIR, ALLOWED_PHOTO_MIME, MAX_PHOTO_SIZE_MB


async def process_upload(conv_id: str, file: UploadFile):
    if file.content_type not in ALLOWED_PHOTO_MIME:
        raise ValueError(f"Unsupported file type: {file.content_type}")

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > MAX_PHOTO_SIZE_MB:
        raise ValueError(f"File too large ({size_mb:.1f}MB). Max {MAX_PHOTO_SIZE_MB}MB")

    ext = os.path.splitext(file.filename or "image.jpg")[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"):
        ext = ".jpg"

    stored_name = f"{uuid.uuid4().hex}{ext}"
    filepath = Path(PHOTOS_DIR) / stored_name
    filepath.write_bytes(contents)

    checksum = hashlib.sha256(contents).hexdigest()

    width = None
    height = None
    try:
        from io import BytesIO
        img = Image.open(BytesIO(contents))
        width, height = img.size
    except Exception:
        pass

    return {
        "original_filename": file.filename,
        "stored_filename": stored_name,
        "mime_type": file.content_type,
        "size_bytes": len(contents),
        "checksum": checksum,
        "width": width,
        "height": height,
    }
