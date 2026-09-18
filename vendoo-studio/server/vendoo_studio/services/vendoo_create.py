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
from vendoo_studio.services.specifics_fill import fill_listing_specifics
from vendoo_studio.services.vendoo_specifics import (
    MERCARI_STATIC_URL,
    FieldSpec,
    mercari_specifics,
    normalize_specifics,
)
from vendoo_studio.services.vendoo_api import (
    build_vendoo_item,
    category_from_hit,
    diff_roundtrip,
    observe_item_schema,
    path_parts,
    pick_category_hit,
)

log = logging.getLogger("vendoo_studio.vendoo_create")

REQUEST_TIMEOUT_SEC = 240.0
SCHEMA_FILE = "vendoo-item-schema.json"
# Marketplaces whose category tree unlocks the rest of that form's fields.
CATEGORY_MARKETPLACES = ("ebay", "etsy", "poshmark", "mercari", "depop")

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


async def probe_schema(job, item_ids: list[str], *, reset: bool = False) -> dict[str, Any]:
    """Read existing items and learn Vendoo's encodings from them.

    Merges with any schema learned before, so every probe only widens what we
    know. Returns the merged schema plus which ids could not be read.

    ``reset`` discards what was learned first. Probing an item Studio created
    itself teaches it its own mistakes — a rejected value read back looks like
    a valid code — so a bad encoding has to be forgettable.
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
    previous = {} if reset else (load_schema() or {})
    merged_fields: dict[str, Any] = {k: dict(v) for k, v in (previous.get("fields") or {}).items()}
    for name, entry in learned["fields"].items():
        target = merged_fields.setdefault(name, {"labels": {}, "codes": [], "shape": entry["shape"]})
        target["labels"] = {**target.get("labels", {}), **entry["labels"]}
        target["codes"] = list(dict.fromkeys([*target.get("codes", []), *entry["codes"]]))
        if entry["shape"] == "object":
            target["shape"] = "object"
    merged_markets: dict[str, Any] = {
        mp: {name: dict(table) for name, table in (entry or {}).items()}
        for mp, entry in (previous.get("marketplaces") or {}).items()
    }
    for mp, entry in learned["marketplaces"].items():
        target = merged_markets.setdefault(mp, {})
        for name, table in entry.items():
            target[name] = {**target.get(name, {}), **table}
    merged_aspects: dict[str, Any] = {mp: dict(shapes) for mp, shapes in (previous.get("aspects") or {}).items()}
    for mp, shapes in learned["aspects"].items():
        target = merged_aspects.setdefault(mp, {})
        for suffix, shape in shapes.items():
            # A list seen once outranks a scalar: multi-select aspects hold one
            # value most of the time.
            if shape == "list" or suffix not in target:
                target[suffix] = shape
    schema = {
        "fields": merged_fields,
        "marketplaces": merged_markets,
        "aspects": merged_aspects,
        "item_count": int(previous.get("item_count") or 0) + learned["item_count"],
        "samples": [item.get("itemID") for item in items if item.get("itemID")][:50],
    }
    save_schema(schema)
    return {"schema": schema, "learned_from": len(items), "failures": failures}


# --------------------------------------------------------------------------
# Category resolution (unlocks marketplace fields the same way a picker does)
# --------------------------------------------------------------------------


def _category_targets(listing: dict[str, Any]) -> list[tuple[str, str, str]]:
    """``(key, marketplace_id, path)`` rows that still need a Vendoo leaf id."""
    targets: list[tuple[str, str, str]] = []
    general_path = str(listing.get("category_path") or "").strip()
    if general_path and not str(listing.get("category_id") or "").strip():
        # General tree uses slug ids (``clothing_shoes__accessories__…``), not
        # eBay numeric leaves — search/lookup against marketplace ``general``.
        targets.append(("general", "general", general_path))

    cats = listing.get("marketplace_categories")
    cats = cats if isinstance(cats, dict) else {}
    ids = listing.get("marketplace_category_ids")
    ids = ids if isinstance(ids, dict) else {}
    for marketplace in CATEGORY_MARKETPLACES:
        path = str(cats.get(marketplace) or "").strip()
        if not path or str(ids.get(marketplace) or "").strip():
            continue
        targets.append((marketplace, marketplace, path))
    return targets


def tree_leaf(marketplace: str, path: str) -> dict[str, Any] | None:
    """Exact leaf from the seeded ``category_tree_nodes`` table, when present."""
    import sqlite3

    from vendoo_studio.config import DATABASE_PATH
    from vendoo_studio.services.vendoo_api import path_parts

    parts = path_parts(path)
    wanted = " > ".join(parts)
    if not wanted:
        return None
    try:
        with sqlite3.connect(DATABASE_PATH) as db:
            row = db.execute(
                "SELECT category_id, path, label, has_children FROM category_tree_nodes "
                "WHERE marketplace = ? AND path = ? AND is_leaf = 1 LIMIT 1",
                (marketplace, wanted),
            ).fetchone()
            if not row:
                return None
            cat_id, node_path, label, has_children = row
            ancestors = _tree_ancestors(db, marketplace, str(cat_id))
    except sqlite3.Error:
        return None
    # Shaped like a ``category_search`` hit so one mapper handles both. The
    # tree has no ``payload_text``, so ``extras`` only comes from a live hit.
    return {
        "id": str(cat_id),
        "is_leaf": True,
        "has_children": bool(has_children),
        "last_subcategory_label": label,
        "all_category_label": path_parts(node_path),
        "parent_category_id_path": ancestors,
    }


def _tree_ancestors(db, marketplace: str, category_id: str) -> list[str]:
    """Ancestor ids root-first, which ``categoryV2.path`` lists before the leaf."""
    chain: list[str] = []
    seen: set[str] = set()
    current = category_id
    while current and current not in seen:
        seen.add(current)
        row = db.execute(
            "SELECT parent_id FROM category_tree_nodes WHERE marketplace = ? AND category_id = ?",
            (marketplace, current),
        ).fetchone()
        if not row or not row[0]:
            break
        parent = str(row[0])
        # The seeded tree hangs every root off a ``__root`` sentinel Vendoo
        # does not store.
        if parent.startswith("__") or parent in ("", "root", "0"):
            break
        chain.append(parent)
        current = parent
    return list(reversed(chain))


async def resolve_listing_categories(job, listing: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Resolve Studio breadcrumbs into Vendoo ``categoryV2`` leaf ids.

    Prefers the local category tree (correct per-marketplace ids). Falls back to
    live ``category_search`` when the path is missing from the tree. Without a
    chosen leaf, Vendoo's UI keeps marketplace/optional fields locked.
    """
    listing = dict(listing)
    unresolved: list[dict[str, str]] = []
    targets = _category_targets(listing)
    if not targets:
        return listing, unresolved

    # Search first: only a live hit carries ``extras.siteId`` and the ancestor
    # id chain, and eBay's form throws without them. The seeded tree is the
    # fallback for when search is unavailable or finds nothing.
    pending_search: list[tuple[str, str, str]] = list(targets)
    resolved_hits: dict[str, dict[str, Any]] = {}

    if pending_search:
        ops = [
            {
                "op": "category_search",
                "text": path,
                # Vendoo's search API names the general tree ``vendoo``.
                "marketplace_id": "vendoo" if marketplace_id == "general" else marketplace_id,
                "throttle_ms": 200,
            }
            for _, marketplace_id, path in pending_search
        ]
        reply = await run_ops(job, ops)
        results = [row for row in reply.get("results", []) if row.get("op") == "category_search"]
        for (key, marketplace_id, path), result in zip(pending_search, results):
            hit = None
            if result.get("ok"):
                matches = list(result.get("matches") or [])
                leaf = result.get("leaf")
                if isinstance(leaf, dict):
                    matches = [leaf, *[m for m in matches if m is not leaf]]
                hit = pick_category_hit(matches, path)
            if not (hit and hit.get("id")):
                hit = tree_leaf(marketplace_id, path)
            if hit and hit.get("id"):
                resolved_hits[key] = hit
            else:
                unresolved.append({"field": f"category:{key}", "value": path})

    ids = dict(listing.get("marketplace_category_ids") or {}) if isinstance(listing.get("marketplace_category_ids"), dict) else {}
    raw = listing.get("marketplace_category_objects")
    objects = dict(raw) if isinstance(raw, dict) else {}
    for key, _marketplace_id, path in targets:
        hit = resolved_hits.get(key)
        resolved = category_from_hit(hit, path)
        if not resolved or not resolved.get("id"):
            if not any(row.get("field") == f"category:{key}" for row in unresolved):
                unresolved.append({"field": f"category:{key}", "value": path})
            continue
        parts = resolved.get("displayPath") or path_parts(path)
        # Keep the whole object: rebuilding it from an id and a breadcrumb
        # drops the fields eBay's form reads.
        objects[key] = resolved
        if key == "general":
            listing["category_id"] = resolved["id"]
            if parts:
                listing["category_path"] = " > ".join(parts)
            continue
        ids[key] = resolved["id"]
        spec_key = f"{key}_specifics"
        specifics = dict(listing.get(spec_key) or {}) if isinstance(listing.get(spec_key), dict) else {}
        specifics["categoryPath"] = parts
        specifics["categoryId"] = resolved["id"]
        listing[spec_key] = specifics

    if ids:
        listing["marketplace_category_ids"] = ids
    if objects:
        listing["marketplace_category_objects"] = objects
    return listing, unresolved


async def mercari_fields(category_id: str) -> dict[str, FieldSpec]:
    """Mercari's size options for one category, from Vendoo's static asset.

    Needs no Vendoo session and no extension — the file is public — so this is
    a plain server-side fetch rather than a browser round trip.
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.get(MERCARI_STATIC_URL, headers={"Accept-Encoding": "gzip"})
            res.raise_for_status()
            master = res.json()
    except Exception as exc:  # noqa: BLE001 - a missing schema is not fatal
        log.info("No Mercari size data: %s", exc)
        return {}
    return mercari_specifics(master, category_id)


async def fetch_listing_specifics(job, listing: dict[str, Any]) -> dict[str, dict[str, FieldSpec]]:
    """Vendoo's own field schema for every leaf this listing resolved.

    This is the call each marketplace form makes as soon as a category is
    picked, and it is the only authority on which fields that category has,
    which are required, which hold a list and which coded option ids are
    legal. One request per marketplace: the extension stops a batch at its
    first failure, and some marketplaces have no schema to serve.

    Answers are cached per leaf, so a category only costs one round trip ever.
    A marketplace that cannot answer is simply left out — ``build_vendoo_item``
    then falls back to what the seller's own items taught us.
    """
    from vendoo_studio.services.category_fields import load_fields, save_fields

    objects = listing.get("marketplace_category_objects")
    objects = objects if isinstance(objects, dict) else {}
    out: dict[str, dict[str, FieldSpec]] = {}
    for marketplace, resolved in objects.items():
        if marketplace == "general" or not isinstance(resolved, dict) or not resolved.get("id"):
            continue
        category_id = str(resolved["id"])
        cached = load_fields(marketplace, category_id)
        if cached:
            out[marketplace] = cached
            continue
        if marketplace == "mercari":
            # Mercari's schema is a public static file, not an API answer.
            specs = await mercari_fields(category_id)
            if specs:
                out[marketplace] = specs
                save_fields(marketplace, category_id, specs)
            continue
        op = {
            "op": "category_specifics",
            "category_id": category_id,
            "marketplace_id": marketplace,
            "path": [str(part) for part in (resolved.get("path") or []) if str(part or "").strip()],
            "extras": resolved.get("extras") if isinstance(resolved.get("extras"), dict) else {},
        }
        try:
            reply = await browser_bridge.request(
                job, "job.vendoo_api", {"ops": [op]}, timeout=REQUEST_TIMEOUT_SEC
            )
        except BrowserBridgeError as exc:
            log.info("No %s category schema: %s", marketplace, exc)
            continue
        hit = next(
            (r for r in (reply.get("results") or []) if r.get("op") == "category_specifics"), {}
        )
        if not hit.get("ok"):
            log.info("No %s category schema: %s", marketplace, hit.get("error") or "empty reply")
            continue
        specs = normalize_specifics(hit.get("specifics"))
        if specs:
            out[marketplace] = specs
            save_fields(marketplace, category_id, specs)
    return out


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


async def create_item(
    job,
    listing: dict[str, Any],
    photos: list[Any],
    *,
    provider=None,
    evidence: str = "",
) -> dict[str, Any]:
    """Create the Vendoo item and verify it round-trips.

    Returns ``{item_id, url, unresolved, diff, unfilled, results}``.
    ``unresolved`` names fields sent as plain text because no encoding covered
    them; ``unfilled`` names category fields still empty when the item went up;
    ``diff`` lists fields Vendoo stored differently from what we sent.

    With a ``provider``, every field the resolved categories render is put to
    the model first, so the item is created once, complete — rather than saved
    bare and filled in afterwards.
    """
    if not photos:
        raise VendooCreateError("Vendoo needs at least one photo")

    schema = load_schema()
    listing, category_unresolved = await resolve_listing_categories(job, listing)
    # Ask each resolved leaf what fields it has before anything is encoded.
    specifics = await fetch_listing_specifics(job, listing)
    listing, unfilled = await fill_listing_specifics(
        listing, specifics, provider, evidence=evidence
    )

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

    item, unresolved = build_vendoo_item(
        listing, schema, images=images, user_id=uid, item_id=item_id, specifics=specifics
    )
    unresolved = [*category_unresolved, *unresolved]

    created = await run_ops(job, [
        {"op": "create_item", "item": item, "subscription_version": subscription_version},
        {"op": "get_item", "item_id": item_id},
    ])
    stored = _result(created, "get_item").get("item")
    diff = diff_roundtrip(item, stored) if isinstance(stored, dict) else []

    return {
        "unfilled": unfilled,
        "item_id": item_id,
        "url": f"https://web.vendoo.co/app/item/{item_id}",
        "unresolved": [entry for entry in unresolved],
        "diff": diff,
        "stored": stored if isinstance(stored, dict) else None,
        "results": [*prep["results"], *created["results"]],
    }
