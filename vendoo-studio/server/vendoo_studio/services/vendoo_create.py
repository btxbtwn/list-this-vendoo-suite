"""Create a Vendoo item from a Studio job the way Vendoo's own form does.

Sequence (all executed by the extension, driven from here):

1. ``session``       — Firebase session from the signed-in web.vendoo.co tab
2. ``upload_photo``  — per photo: inventory service signed PUT → ``{version:3, id}``
3. ``new_item_id``   — Firestore-style id, minted client-side like the form
4. ``create_item``   — ``items`` Cloud Function, ``{type: "createItem"}``
5. ``get_item``      — read it back and diff against what we sent

Nothing here lists to a marketplace; the item is a Vendoo draft the seller
reviews in Vendoo, which keeps the AGENTS.md invariant intact.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from vendoo_studio.config import DATA_DIR, HOST, PORT
from vendoo_studio.services import browser_bridge
from vendoo_studio.services.browser_bridge import BrowserBridgeError
from vendoo_studio.services.vendoo_api import (
    build_vendoo_item,
    diff_roundtrip,
    observe_item_schema,
)

log = logging.getLogger("vendoo_studio.vendoo_create")

REQUEST_TIMEOUT_SEC = 240.0
SCHEMA_FILE = "vendoo-item-schema.json"

__all__ = ["BrowserBridgeError", "VendooCreateError", "create_item", "probe_schema", "load_schema"]


class VendooCreateError(RuntimeError):
    def __init__(self, message: str, *, results: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.results = results or []


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------


async def run_ops(job, ops: list[dict[str, Any]]) -> dict[str, Any]:
    """Send one ``job.vendoo_api`` message and return its reply."""
    reply = await browser_bridge.request(job, "job.vendoo_api", {"ops": ops}, timeout=REQUEST_TIMEOUT_SEC)
    results = reply.get("results") if isinstance(reply.get("results"), list) else []
    if not reply.get("ok"):
        failed = next((r for r in results if not r.get("ok")), None)
        message = (failed or {}).get("error") or reply.get("error") or "Vendoo API call failed"
        raise VendooCreateError(str(message), results=results)
    return reply


def _result(reply: dict[str, Any], op: str, index: int = 0) -> dict[str, Any]:
    matches = [r for r in reply.get("results", []) if r.get("op") == op]
    if len(matches) <= index:
        raise VendooCreateError(f"Vendoo API reply is missing {op}", results=reply.get("results", []))
    return matches[index]


# --------------------------------------------------------------------------
# Schema (learned from the user's own items)
# --------------------------------------------------------------------------


def schema_path() -> Path:
    return Path(DATA_DIR) / SCHEMA_FILE


def load_schema() -> dict[str, Any] | None:
    path = schema_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save_schema(schema: dict[str, Any]) -> Path:
    path = schema_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
    return path


async def probe_schema(job, item_ids: list[str]) -> dict[str, Any]:
    """Read existing items and learn Vendoo's encodings from them.

    Merges with any schema learned before, so every probe only widens what we
    know. Returns the merged schema plus which ids could not be read.
    """
    ids = [str(item_id).strip() for item_id in item_ids if str(item_id or "").strip()]
    if not ids:
        raise VendooCreateError("Probe needs at least one Vendoo item id")
    ops = [{"op": "get_item", "item_id": item_id, "throttle_ms": 250} for item_id in ids]
    reply = await browser_bridge.request(job, "job.vendoo_api", {"ops": ops}, timeout=REQUEST_TIMEOUT_SEC)
    results = reply.get("results") if isinstance(reply.get("results"), list) else []
    items = [r["item"] for r in results if r.get("ok") and isinstance(r.get("item"), dict)]
    failures = [{"item_id": r.get("item_id"), "error": r.get("error")} for r in results if not r.get("ok")]
    if not items and not results and reply.get("error"):
        raise VendooCreateError(str(reply["error"]))

    learned = observe_item_schema(items)
    previous = load_schema() or {"fields": {}, "item_count": 0}
    merged_fields: dict[str, Any] = {k: dict(v) for k, v in (previous.get("fields") or {}).items()}
    for name, entry in learned["fields"].items():
        target = merged_fields.setdefault(name, {"labels": {}, "codes": [], "shape": entry["shape"]})
        target["labels"] = {**target.get("labels", {}), **entry["labels"]}
        target["codes"] = list(dict.fromkeys([*target.get("codes", []), *entry["codes"]]))
        if entry["shape"] == "object":
            target["shape"] = "object"
    schema = {
        "fields": merged_fields,
        "item_count": int(previous.get("item_count") or 0) + learned["item_count"],
        "samples": [item.get("itemID") for item in items if item.get("itemID")][:50],
    }
    save_schema(schema)
    return {"schema": schema, "learned_from": len(items), "failures": failures}


# --------------------------------------------------------------------------
# Create
# --------------------------------------------------------------------------


def _photo_ops(job, photos: list[Any]) -> list[dict[str, Any]]:
    ops = []
    for photo in photos:
        extension = "jpg"
        mime = str(getattr(photo, "mime_type", "") or "").lower()
        if "png" in mime:
            extension = "png"
        elif "webp" in mime:
            extension = "webp"
        elif "gif" in mime:
            extension = "gif"
        width = int(getattr(photo, "width", 0) or 0)
        height = int(getattr(photo, "height", 0) or 0)
        ops.append({
            "op": "upload_photo",
            "photo": {
                "id": photo.id,
                "url": f"http://{HOST}:{PORT}/api/jobs/{job.id}/photos/{photo.id}",
                "mime_type": mime or "image/jpeg",
                "extension": extension,
                "max_dimension": max(width, height),
            },
        })
    return ops


async def create_item(job, listing: dict[str, Any], photos: list[Any]) -> dict[str, Any]:
    """Create the Vendoo item and verify it round-trips.

    Returns ``{item_id, url, unresolved, diff, results}``. ``unresolved`` names
    fields sent as plain text because no encoding was learned for them yet;
    ``diff`` lists fields Vendoo stored differently from what we sent.
    """
    if not photos:
        raise VendooCreateError("Vendoo needs at least one photo")

    schema = load_schema()

    # Photos and the id first: the item body references both.
    prep = await run_ops(job, [{"op": "session"}, {"op": "new_item_id"}, {"op": "subscription"}, *_photo_ops(job, photos)])
    uid = str(_result(prep, "session").get("uid") or "")
    item_id = str(_result(prep, "new_item_id").get("item_id") or "")
    subscription_version = _result(prep, "subscription").get("version")
    images = [r["image"] for r in prep["results"] if r.get("op") == "upload_photo" and r.get("image")]
    if not uid or not item_id:
        raise VendooCreateError("Vendoo session or item id missing", results=prep["results"])
    if len(images) != len(photos):
        raise VendooCreateError(f"Only {len(images)} of {len(photos)} photos uploaded", results=prep["results"])

    item, unresolved = build_vendoo_item(listing, schema, images=images, user_id=uid, item_id=item_id)

    created = await run_ops(job, [
        {"op": "create_item", "item": item, "subscription_version": subscription_version},
        {"op": "get_item", "item_id": item_id},
    ])
    stored = _result(created, "get_item").get("item")
    diff = diff_roundtrip(item, stored) if isinstance(stored, dict) else []

    return {
        "item_id": item_id,
        "url": f"https://web.vendoo.co/app/item/{item_id}",
        "unresolved": [entry for entry in unresolved],
        "diff": diff,
        "stored": stored if isinstance(stored, dict) else None,
        "results": [*prep["results"], *created["results"]],
    }
