from __future__ import annotations

import json
import threading
from pathlib import Path

from vendoo_studio.config import user_data_root

# Order used when filling Vendoo marketplace forms.
FILLABLE_MARKETPLACES = ("ebay", "etsy", "poshmark", "mercari", "depop")

# Marketplaces shown in Settings and Fields. `fillable` ones have Send-to-Vendoo form fillers.
MARKETPLACE_CATALOG: tuple[tuple[str, str, bool], ...] = (
    ("ebay", "eBay", True),
    ("poshmark", "Poshmark", True),
    ("mercari", "Mercari", True),
    ("depop", "Depop", True),
    ("etsy", "Etsy", True),
    ("facebook", "Facebook", False),
    ("grailed", "Grailed", False),
    ("whatnot", "Whatnot", False),
    ("shopify", "Shopify", False),
)

KNOWN_MARKETPLACES = tuple(item[0] for item in MARKETPLACE_CATALOG)
DEFAULT_SELECTED = list(FILLABLE_MARKETPLACES)

_lock = threading.Lock()


def settings_path() -> Path:
    return user_data_root() / "settings.json"


def marketplace_label(marketplace_id: str) -> str:
    for item_id, label, _fillable in MARKETPLACE_CATALOG:
        if item_id == marketplace_id:
            return label
    return marketplace_id[:1].upper() + marketplace_id[1:] if marketplace_id else marketplace_id


def catalog_payload() -> list[dict]:
    return [
        {"id": item_id, "label": label, "fillable": fillable}
        for item_id, label, fillable in MARKETPLACE_CATALOG
    ]


def normalize_selected(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return list(DEFAULT_SELECTED)
    chosen = {str(item).strip().lower() for item in raw if str(item).strip()}
    unknown = sorted(chosen - set(KNOWN_MARKETPLACES))
    if unknown:
        raise ValueError(f"Unknown marketplace: {', '.join(unknown)}")
    return [item_id for item_id in KNOWN_MARKETPLACES if item_id in chosen]


def _read_settings() -> dict:
    path = settings_path()
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_settings(payload: dict) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def get_selected_marketplaces() -> list[str]:
    with _lock:
        payload = _read_settings()
    if "marketplaces" not in payload:
        return list(DEFAULT_SELECTED)
    try:
        return normalize_selected(payload.get("marketplaces"))
    except ValueError:
        return list(DEFAULT_SELECTED)


def set_selected_marketplaces(selected: object) -> list[str]:
    normalized = normalize_selected(selected)
    with _lock:
        payload = _read_settings()
        payload["marketplaces"] = normalized
        _write_settings(payload)
    return normalized


def selected_fillable_platforms(selected: list[str] | None = None) -> list[str]:
    chosen = set(selected if selected is not None else get_selected_marketplaces())
    return [marketplace for marketplace in FILLABLE_MARKETPLACES if marketplace in chosen]
