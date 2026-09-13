from __future__ import annotations

import json
import threading
from pathlib import Path

from vendoo_studio.config import user_data_root

_lock = threading.Lock()
SETUP_GUIDE_DISMISSED_KEY = "setup_guide_dismissed"


def settings_path() -> Path:
    return user_data_root() / "settings.json"


def _read_unlocked() -> dict:
    path = settings_path()
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_unlocked(payload: dict) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def read_settings() -> dict:
    with _lock:
        return _read_unlocked()


def write_settings(payload: dict) -> None:
    with _lock:
        _write_unlocked(payload)


def update_settings(mutator) -> dict:
    with _lock:
        payload = _read_unlocked()
        mutator(payload)
        _write_unlocked(payload)
        return payload


def setup_guide_dismissed() -> bool:
    return bool(read_settings().get(SETUP_GUIDE_DISMISSED_KEY))


def dismiss_setup_guide() -> dict:
    def mutator(payload: dict) -> None:
        payload[SETUP_GUIDE_DISMISSED_KEY] = True

    update_settings(mutator)
    return {"ok": True, "dismissed": True}
