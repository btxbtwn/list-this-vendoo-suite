from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from fastapi import UploadFile
from PIL import Image

from vendoo_studio.config import PHOTOS_DIR, ALLOWED_PHOTO_MIME, MAX_PHOTO_SIZE_MB

MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
}


def stored_photo_path(stored_filename: str) -> Path:
    root = Path(PHOTOS_DIR).resolve()
    path = (root / Path(stored_filename).name).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Invalid photo path") from exc
    return path


def _normalize_mime(content_type: str | None, contents: bytes) -> str:
    raw = (content_type or "").split(";")[0].strip().lower()
    if raw == "image/jpg":
        raw = "image/jpeg"
    if raw in ALLOWED_PHOTO_MIME:
        return raw
    if contents.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if contents.startswith(b"\x89PNG"):
        return "image/png"
    if contents.startswith(b"RIFF") and b"WEBP" in contents[:16]:
        return "image/webp"
    raise ValueError(f"Unsupported file type: {content_type}")


def process_bytes(contents: bytes, filename: str | None = None, content_type: str | None = None) -> dict:
    mime_type = _normalize_mime(content_type, contents)
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > MAX_PHOTO_SIZE_MB:
        raise ValueError(f"File too large ({size_mb:.1f}MB). Max {MAX_PHOTO_SIZE_MB}MB")

    ext = os.path.splitext(filename or "image.jpg")[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"):
        ext = MIME_EXTENSIONS.get(mime_type, ".jpg")

    stored_name = f"{uuid.uuid4().hex}{ext}"
    filepath = stored_photo_path(stored_name)
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
        "original_filename": filename or stored_name,
        "stored_filename": stored_name,
        "mime_type": mime_type,
        "size_bytes": len(contents),
        "checksum": checksum,
        "width": width,
        "height": height,
    }


async def process_upload(conv_id: str, file: UploadFile):
    contents = await file.read()
    return process_bytes(contents, file.filename, file.content_type)
