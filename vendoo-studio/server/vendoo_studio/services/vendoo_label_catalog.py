"""Persistent Vendoo inventory-label id → display-name map.

An item's ``labels`` array is Firestore ids. Item Details should show names.
``list_labels`` is the source of truth, but Regenerate cannot wait on a silent
Chrome — and once that read times out, raw ids stick in notes forever.

This cache is filled whenever Studio learns a mapping (catalog read,
``labelDetails`` on an imported item, name→id resolve for save). Later lookups
use it first so opaque ids still become "Women" / "To List" when Chrome is
quiet.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger("vendoo_studio.vendoo_label_catalog")

CATALOG_FILE = "vendoo-label-catalog.json"
# Vendoo mints label ids the same way as item ids: 20 chars, A–Z a–z 0–9.
_FIRESTORE_ID_RE = re.compile(r"^[A-Za-z0-9]{20}$")

_lock = threading.Lock()
_memory: dict[str, str] | None = None


def catalog_path() -> Path:
    from vendoo_studio.config import DATA_DIR

    return Path(DATA_DIR) / CATALOG_FILE


def looks_like_label_id(value: str) -> bool:
    """True for an opaque Vendoo label id, not a seller-facing name."""
    return bool(_FIRESTORE_ID_RE.fullmatch(str(value or "").strip()))


def _read_disk() -> dict[str, str]:
    path = catalog_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("Vendoo label catalog unreadable: %s", exc)
        return {}
    by_id: dict[str, str] = {}
    if isinstance(data, dict):
        raw = data.get("by_id") if isinstance(data.get("by_id"), dict) else data
        if isinstance(raw, dict):
            for key, value in raw.items():
                label_id = str(key or "").strip()
                name = str(value or "").strip()
                if label_id and name:
                    by_id[label_id] = name
    return by_id


def _write_disk(by_id: dict[str, str]) -> None:
    path = catalog_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"by_id": by_id}, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError as exc:
        log.warning("Vendoo label catalog not saved: %s", exc)


def load() -> dict[str, str]:
    """id → name. Empty when nothing has been learned yet."""
    global _memory
    with _lock:
        if _memory is None:
            _memory = _read_disk()
        return dict(_memory)


def remember(pairs: dict[str, str] | list[dict[str, Any]] | None) -> dict[str, str]:
    """Merge newly learned id→name pairs onto disk. Returns the full catalog."""
    global _memory
    incoming: dict[str, str] = {}
    if isinstance(pairs, dict):
        for key, value in pairs.items():
            label_id = str(key or "").strip()
            name = str(value or "").strip()
            if label_id and name and label_id != name:
                incoming[label_id] = name
    elif isinstance(pairs, list):
        for row in pairs:
            if not isinstance(row, dict):
                continue
            label_id = str(row.get("id") or "").strip()
            name = str(
                row.get("name") or row.get("displayName") or row.get("label") or ""
            ).strip()
            if label_id and name and label_id != name:
                incoming[label_id] = name
    if not incoming:
        return load()

    with _lock:
        current = dict(_memory) if _memory is not None else _read_disk()
        merged = {**current, **incoming}
        if merged != current:
            _write_disk(merged)
        _memory = merged
        return dict(merged)


def apply(labels: list[Any], names: dict[str, str] | None = None) -> list[str]:
    """Replace ids with names where known; unknown values pass through."""
    catalog = names if names is not None else load()
    cleaned = [str(label).strip() for label in (labels or []) if str(label).strip()]
    return [catalog.get(label, label) for label in cleaned]


def has_opaque_ids(labels: list[Any]) -> bool:
    return any(looks_like_label_id(str(label).strip()) for label in (labels or []) if str(label).strip())


def clear_for_tests() -> None:
    """Drop the in-memory + on-disk catalog. Tests only."""
    global _memory
    with _lock:
        _memory = {}
        path = catalog_path()
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
