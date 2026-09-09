import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = str(BASE_DIR / "data")
PHOTOS_DIR = str(BASE_DIR / "data" / "photos")
FILL_LOGS_DIR = str(BASE_DIR / "data" / "fill-logs")
DATABASE_PATH = str(BASE_DIR / "data" / "vendoo_studio.db")

os.makedirs(PHOTOS_DIR, exist_ok=True)
os.makedirs(FILL_LOGS_DIR, exist_ok=True)

HOST = os.environ.get("VENDOO_STUDIO_HOST", "127.0.0.1")
PORT = int(os.environ.get("VENDOO_STUDIO_PORT", "4318"))

MAX_PHOTO_COUNT = 20
MAX_PHOTO_SIZE_MB = 20
ALLOWED_PHOTO_MIME = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}

CORS_ORIGINS = [
    f"http://{HOST}:{PORT}",
    f"http://{HOST}:5173",
    "https://web.vendoo.co",
    "https://app.vendoo.co",
    "https://www.ebay.com",
    "https://poshmark.com",
    "https://www.mercari.com",
    "https://www.depop.com",
    "https://www.etsy.com",
]
