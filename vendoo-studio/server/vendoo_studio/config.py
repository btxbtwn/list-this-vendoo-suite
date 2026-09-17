from __future__ import annotations

import json
import os
import sys
from pathlib import Path

CHANNELS = {
    "production": {
        "app_name": "List This Studio",
        "bundle_id": "local.listthis.studio",
        "release_tag": "studio-macos",
        "port": 4318,
        "extension_suffix": "",
    },
    "staging": {
        "app_name": "List This Studio Staging",
        "bundle_id": "local.listthis.studio.staging",
        "release_tag": "studio-macos-staging",
        "port": 4319,
        "extension_suffix": " (Staging)",
    },
}


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None))


def is_packaged() -> bool:
    if is_frozen():
        return True
    return os.environ.get("VENDOO_STUDIO_PACKAGED", "") == "1"


def resource_root() -> Path:
    override = os.environ.get("VENDOO_STUDIO_RESOURCE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen():
        meipass = Path(sys._MEIPASS)
        resources = Path(sys.executable).resolve().parent.parent / "Resources"
        if (meipass / "dist" / "index.html").is_file():
            return meipass
        if (resources / "dist" / "index.html").is_file():
            return resources
        return meipass
    return Path(__file__).resolve().parent.parent.parent


def channel_name() -> str:
    """Release channel: env override, else the channel stamped into build_info.json."""
    name = os.environ.get("VENDOO_STUDIO_CHANNEL")
    if not name:
        try:
            name = json.loads((resource_root() / "build_info.json").read_text(encoding="utf-8")).get("channel")
        except (OSError, json.JSONDecodeError):
            name = None
    return name if name in CHANNELS else "production"


CHANNEL_NAME = channel_name()
CHANNEL = CHANNELS[CHANNEL_NAME]
APP_NAME = CHANNEL["app_name"]
BUNDLE_ID = CHANNEL["bundle_id"]


def user_data_root() -> Path:
    override = os.environ.get("VENDOO_STUDIO_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if is_packaged():
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return resource_root() / "data"


def skills_dir() -> Path:
    override = os.environ.get("VENDOO_STUDIO_SKILLS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    bundled = resource_root() / "skills"
    if (bundled / "list-this" / "SKILL.md").exists():
        return bundled
    return resource_root().parent / "skills"


def extension_source_dir() -> Path:
    override = os.environ.get("VENDOO_STUDIO_EXTENSION_DIR")
    if override:
        return Path(override).expanduser().resolve()
    bundled = resource_root() / "vendoo-extension"
    if (bundled / "manifest.json").exists():
        return bundled
    return resource_root().parent / "vendoo-extension"


def frontend_dist_dir() -> Path:
    return resource_root() / "dist"


def log_path() -> Path:
    return user_data_root() / "logs" / f"{APP_NAME}.log"


BASE_DIR = resource_root()
DATA_DIR = str(user_data_root())
PHOTOS_DIR = str(user_data_root() / "photos")
FILL_LOGS_DIR = str(user_data_root() / "fill-logs")
LOGS_DIR = str(user_data_root() / "logs")
DATABASE_PATH = str(user_data_root() / "vendoo_studio.db")
PAIRING_FILE = str(user_data_root() / "pairing_token.txt")


def ensure_user_data_dirs() -> None:
    user_data_root().mkdir(parents=True, exist_ok=True)
    Path(PHOTOS_DIR).mkdir(parents=True, exist_ok=True)
    Path(FILL_LOGS_DIR).mkdir(parents=True, exist_ok=True)
    Path(LOGS_DIR).mkdir(parents=True, exist_ok=True)


ensure_user_data_dirs()

HOST = os.environ.get("VENDOO_STUDIO_HOST", "127.0.0.1")
PORT = int(os.environ.get("VENDOO_STUDIO_PORT", CHANNEL["port"]))

MAX_PHOTO_COUNT = 20
MAX_PHOTO_SIZE_MB = 20
ALLOWED_PHOTO_MIME = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}

CORS_ORIGINS = [
    f"http://{HOST}:{PORT}",
    f"http://{HOST}:5173",
]
