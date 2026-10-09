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

import asyncio
import copy
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from vendoo_studio.config import DATA_DIR, HOST, PORT
from vendoo_studio.services import browser_bridge
from vendoo_studio.services.browser_bridge import BrowserBridgeError
from vendoo_studio.services.vendoo_send import checkpoint, measure_stage, pending_send
from vendoo_studio.services.specifics_fill import fill_listing_specifics, specifics_gaps
from vendoo_studio.services.vendoo_specifics import (
    MERCARI_STATIC_URL,
    FieldSpec,
    mercari_specifics,
    normalize_specifics,
    specs_to_rows,
)
from vendoo_studio.services.vendoo_api import (
    build_vendoo_item,
    category_from_hit,
    category_v2,
    changed_fields,
    pick_mapped_category,
    diff_roundtrip,
    diff_updates,
    hit_display_path,
    observe_item_schema,
    path_parts,
    pick_category_hit,
)

log = logging.getLogger("vendoo_studio.vendoo_create")

REQUEST_TIMEOUT_SEC = 240.0
# Reads that only decorate the result must not hold up the caller for as long as
# a form fill may legitimately take.
LOOKUP_TIMEOUT_SEC = 10.0
# Reading one item. Normally under a second; the slow case is the extension
# opening a Vendoo tab to refresh the sign-in. Opening a listing makes these
# reads, and each one holds one of the webview's six connections to Studio,
# so they cannot wait as long as a write does.
ITEM_READ_TIMEOUT_SEC = 45.0
SCHEMA_FILE = "vendoo-item-schema.json"
# Marketplaces whose category tree unlocks the rest of that form's fields.
CATEGORY_MARKETPLACES = ("ebay", "etsy", "poshmark", "mercari", "depop", "grailed", "vinted", "facebook")
_specifics_requests: dict[tuple, asyncio.Task] = {}

__all__ = ["BrowserBridgeError", "VendooCreateError", "create_item", "probe_schema", "load_schema"]


class VendooCreateError(RuntimeError):
    def __init__(self, message: str, *, results: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.results = results or []


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------


async def run_ops(
    job, ops: list[dict[str, Any]], *, timeout: float = REQUEST_TIMEOUT_SEC
) -> dict[str, Any]:
    """Send one ``job.vendoo_api`` message and return its reply."""
    stage = "+".join(dict.fromkeys(op["op"] for op in ops))
    with measure_stage(job, stage):
        reply = await browser_bridge.request(job, "job.vendoo_api", {"ops": ops}, timeout=timeout)
        if not reply.get("ok"):
            results = reply.get("results") or []
            failed = next((r for r in results if not r.get("ok")), None)
            message = (failed or {}).get("error") or reply.get("error") or "Vendoo API call failed"
            raise VendooCreateError(str(message), results=results)
    results = reply.get("results") if isinstance(reply.get("results"), list) else []
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
    ops = [{"op": "get_item", "item_id": item_id} for item_id in ids]
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


def _mappable_marketplaces() -> tuple[str, ...]:
    """Marketplaces the seller lists on, which are the ones worth mapping to."""
    try:
        from vendoo_studio.services.marketplaces import selected_fillable_platforms

        return tuple(selected_fillable_platforms())
    except Exception:  # noqa: BLE001 - settings are not worth failing a create over
        return ()


def _category_targets(listing: dict[str, Any]) -> list[tuple[str, str, str]]:
    """``(key, marketplace_id, path)`` rows that still need a Vendoo leaf id."""
    targets: list[tuple[str, str, str]] = []
    general_path = str(listing.get("category_path") or "").strip()
    if general_path and not str(listing.get("category_id") or "").strip():
        # General tree uses slug ids (``clothing_shoes__accessories__…``), not
        # eBay numeric leaves — search/lookup against marketplace ``general``.
        targets.append(("general", "general", general_path))

    from vendoo_studio.services.registry import CATEGORY_PATH_MAPPERS

    cats = listing.get("marketplace_categories")
    cats = cats if isinstance(cats, dict) else {}
    ids = listing.get("marketplace_category_ids")
    ids = ids if isinstance(ids, dict) else {}
    for marketplace in CATEGORY_MARKETPLACES:
        if str(ids.get(marketplace) or "").strip():
            continue
        path = str(cats.get(marketplace) or "").strip()
        # These trees do not hold every wording the generator uses ("Tops",
        # "Button-Down Shirts"); map onto a selectable leaf before anything
        # resolves against it. With no breadcrumb of its own, the general
        # category is the cue — Vendoo maps that one Women's Tops leaf onto a
        # single leaf per marketplace, so naming the leaf this garment wants
        # is the only way its T-shirts leaf is ever asked for.
        mapper = CATEGORY_PATH_MAPPERS.get(marketplace)
        if mapper and (path or marketplace in _mappable_marketplaces()):
            mapped_path = str(mapper(path or general_path, listing) or "").strip()
            if path:
                path = mapped_path or path
            elif mapped_path and mapped_path != general_path:
                path = mapped_path
        if not path:
            # No breadcrumb of its own is fine now: the mapper works from the
            # general category. Only for marketplaces the seller actually
            # lists on, and quietly — searching needs text, so these go
            # unresolved-free when nothing maps.
            if marketplace in _mappable_marketplaces() and (
                general_path or str(listing.get("category_id") or "").strip()
            ):
                targets.append((marketplace, marketplace, ""))
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


async def _hits_by_search(
    job,
    targets: list[tuple[str, str, str]],
    unresolved: list[dict[str, str]],
    *, timeout: float = REQUEST_TIMEOUT_SEC,
) -> dict[str, dict[str, Any]]:
    """Resolve each target on its own, by live search then the seeded tree.

    Only a live hit carries ``extras.siteId`` and the ancestor id chain, and
    eBay's form throws without them; the tree covers search being unavailable.
    """
    # A mapping-only target has no text to search for.
    searchable = [row for row in targets if str(row[2] or "").strip()]
    if not searchable:
        return {}
    ops = [
        {
            "op": "category_search",
            "text": path,
            # Vendoo's search API names the general tree ``vendoo``.
            "marketplace_id": "vendoo" if marketplace_id == "general" else marketplace_id,
        }
        for _, marketplace_id, path in searchable
    ]
    reply = await run_ops(job, ops, timeout=timeout)
    results = [row for row in reply.get("results", []) if row.get("op") == "category_search"]
    hits: dict[str, dict[str, Any]] = {}
    for (key, marketplace_id, path), result in zip(searchable, results, strict=True):
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
            hits[key] = hit
        else:
            unresolved.append({"field": f"category:{key}", "value": path})
    return hits


def _agrees_with_path(hit: dict[str, Any], path: str) -> bool:
    """True when a mapped hit lands on the leaf the breadcrumb named.

    Leaf wording only: Vendoo's tree and the breadcrumb often disagree about
    the ancestors ("Women > Tops" vs "Women's Clothing > Tops") while naming
    the same leaf, and it is the leaf that decides the form.
    """
    wanted = path_parts(path)
    parts = [str(part) for part in hit_display_path(hit)]
    if not wanted or not parts:
        return True
    return _leaf_key(parts[-1]) == _leaf_key(wanted[-1])


def _leaf_key(leaf: str) -> str:
    return "".join(ch for ch in str(leaf).lower() if ch.isalnum())


async def _hits_by_mapping(
    job,
    general: dict[str, Any],
    targets: list[tuple[str, str, str]],
    *, timeout: float = REQUEST_TIMEOUT_SEC,
) -> dict[str, dict[str, Any]]:
    """Ask Vendoo which category each marketplace uses for this general one.

    Vendoo's forms map from the general category rather than choosing per
    marketplace, and so should we: searching each marketplace for the same
    listing text means six chances to land somewhere unrelated, when the
    answer is a property of the general category. A marketplace the mapper
    has nothing for is left out, for the caller to resolve the old way.
    """
    if not (general.get("id") and targets):
        return {}
    ops = [
        {
            "op": "category_map",
            "marketplace_id": key,
            "general_category": general,
        }
        for key, _marketplace_id, _path in targets
    ]
    try:
        reply = await browser_bridge.request(job, "job.vendoo_api", {"ops": ops}, timeout=timeout)
    except BrowserBridgeError as exc:
        log.info("category mapper unavailable: %s", exc)
        return {}
    wanted = {key: path for key, _marketplace_id, path in targets}
    hits: dict[str, dict[str, Any]] = {}
    for row in reply.get("results") or []:
        if row.get("op") != "category_map" or not row.get("ok"):
            continue
        # Its single match is sometimes the wrong branch; the alternates it
        # returns alongside are worth reading before taking it — against this
        # marketplace's own breadcrumb when the listing named one.
        key = str(row.get("marketplace_id"))
        best = pick_mapped_category(
            general,
            row.get("match"),
            row.get("recommendations"),
            want_path=wanted.get(key, ""),
        )
        if isinstance(best, dict) and best.get("id"):
            hits[str(row.get("marketplace_id"))] = best
    return hits


async def resolve_listing_categories(
    job, listing: dict[str, Any], *, timeout: float = REQUEST_TIMEOUT_SEC,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Resolve Studio breadcrumbs into Vendoo ``categoryV2`` leaf ids.

    The general category is settled first, then Vendoo maps it to each
    marketplace. Anything it will not map falls back to searching that
    marketplace directly. Without a chosen leaf, Vendoo's UI keeps
    marketplace/optional fields locked.
    """
    listing = dict(listing)
    unresolved: list[dict[str, str]] = []
    targets = _category_targets(listing)
    if not targets:
        return listing, unresolved

    general_target = next((row for row in targets if row[0] == "general"), None)
    market_targets = [row for row in targets if row[0] != "general"]

    resolved_hits: dict[str, dict[str, Any]] = {}
    general_v2: dict[str, Any] | None = None
    if general_target:
        resolved_hits.update(await _hits_by_search(job, [general_target], unresolved, timeout=timeout))
        general_v2 = category_from_hit(resolved_hits.get("general"), general_target[2])
    else:
        # Already resolved on the listing — still enough to map from.
        objects = listing.get("marketplace_category_objects")
        if isinstance(objects, dict) and isinstance(objects.get("general"), dict):
            general_v2 = objects["general"]
        elif listing.get("category_id"):
            general_v2 = category_v2(listing.get("category_id"), listing.get("category_path"))

    disagreed: list[tuple[str, str, str]] = []
    if general_v2 and market_targets:
        mapped = await _hits_by_mapping(job, general_v2, market_targets, timeout=timeout)
        resolved_hits.update(mapped)
        # A mapped leaf that contradicts the breadcrumb this listing named is
        # the mapper guessing a subtype the seller did not ask for. Search for
        # the breadcrumb itself; the mapped leaf stays as the fallback.
        disagreed = [
            row for row in market_targets
            if row[0] in mapped and row[2] and not _agrees_with_path(mapped[row[0]], row[2])
        ]
        market_targets = [row for row in market_targets if row[0] not in mapped]

    if market_targets:
        resolved_hits.update(await _hits_by_search(job, market_targets, unresolved, timeout=timeout))
    if disagreed:
        # Failures here are not worth reporting: the mapped leaf still stands,
        # and so it does unless the search landed on the leaf that was asked
        # for — a near miss is no better than the mapper's own guess.
        searched = await _hits_by_search(job, disagreed, [], timeout=timeout)
        for key, _marketplace_id, path in disagreed:
            hit = searched.get(key)
            if hit and _agrees_with_path(hit, path):
                resolved_hits[key] = hit

    ids = dict(listing.get("marketplace_category_ids") or {}) if isinstance(listing.get("marketplace_category_ids"), dict) else {}
    raw = listing.get("marketplace_category_objects")
    objects = dict(raw) if isinstance(raw, dict) else {}
    for key, _marketplace_id, path in targets:
        hit = resolved_hits.get(key)
        resolved = category_from_hit(hit, path) if hit else None
        if not resolved or not resolved.get("id"):
            # Only a breadcrumb the seller actually chose is worth reporting.
            if path and not any(row.get("field") == f"category:{key}" for row in unresolved):
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


async def fetch_listing_specifics(
    job, listing: dict[str, Any], *, timeout: float = REQUEST_TIMEOUT_SEC
) -> dict[str, dict[str, FieldSpec]]:
    """Vendoo's own field schema for every leaf this listing resolved.

    This is the call each marketplace form makes as soon as a category is
    picked, and it is the only authority on which fields that category has,
    which are required, which hold a list and which coded option ids are
    legal. One request per marketplace, all in flight at once: the extension
    stops a batch at its first failure, and some marketplaces have no schema
    to serve.

    Answers are cached per leaf for seven days; concurrent lookups share a request.
    A marketplace that cannot answer is simply left out — ``build_vendoo_item``
    then falls back to what the seller's own items taught us.
    """
    from vendoo_studio.services.category_fields import listing_category_ids

    objects = listing.get("marketplace_category_objects")
    objects = objects if isinstance(objects, dict) else {}
    # Whole category objects only exist once a create has resolved them. During
    # generation the listing carries breadcrumbs, and those resolve against the
    # seeded tree — without this the schema looks unavailable and the caller
    # falls back to discovering fields through a browser.
    # marketplace -> (leaf id, whole category object when we have one). The
    # object carries the ancestor path and extras eBay's schema lookup wants;
    # a breadcrumb-resolved leaf has the id only, which the endpoint accepts.
    leaves: dict[str, tuple[str, dict[str, Any]]] = {
        marketplace: (str(resolved["id"]), resolved)
        for marketplace, resolved in objects.items()
        if isinstance(resolved, dict) and resolved.get("id")
    }
    for marketplace, category_id in listing_category_ids(listing).items():
        leaves.setdefault(marketplace, (category_id, {}))

    found = await asyncio.gather(*(
        fetch_leaf_specifics(job, marketplace, category_id, resolved, timeout=timeout)
        for marketplace, (category_id, resolved) in leaves.items()
    ))
    return {marketplace: specs for marketplace, specs in zip(leaves, found, strict=True) if specs}


async def fetch_leaf_specifics(
    job,
    marketplace: str,
    category_id: str,
    resolved: dict[str, Any] | None = None,
    *,
    timeout: float = REQUEST_TIMEOUT_SEC,
) -> dict[str, FieldSpec]:
    """Share concurrent requests for the same leaf and lookup context."""
    key = (asyncio.get_running_loop(), marketplace, category_id, json.dumps(resolved or {}, sort_keys=True))
    task = _specifics_requests.get(key)
    if task is None:
        task = asyncio.create_task(_fetch_leaf_specifics(job, marketplace, category_id, resolved, timeout=timeout))
        _specifics_requests[key] = task
        task.add_done_callback(lambda _task: _specifics_requests.pop(key, None))
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
    except TimeoutError:
        return {}


async def _fetch_leaf_specifics(
    job,
    marketplace: str,
    category_id: str,
    resolved: dict[str, Any] | None = None,
    *,
    timeout: float = REQUEST_TIMEOUT_SEC,
) -> dict[str, FieldSpec]:
    """Vendoo's schema for one marketplace leaf: cached, else asked for and stored.

    Empty when the leaf has no schema or Chrome cannot answer in ``timeout``.
    """
    from vendoo_studio.services.category_fields import load_fields, save_fields

    if not category_id:
        return {}
    cached = load_fields(marketplace, category_id)
    if cached is not None or marketplace == "general":
        return cached or {}
    if marketplace == "mercari":
        # Mercari's schema is a public static file, not an API answer.
        specs = await mercari_fields(category_id)
        if specs:
            save_fields(marketplace, category_id, specs)
        return specs
    resolved = resolved or {}
    op = {
        "op": "category_specifics",
        "category_id": category_id,
        "marketplace_id": marketplace,
        "path": [str(part) for part in (resolved.get("path") or []) if str(part or "").strip()],
        "extras": resolved.get("extras") if isinstance(resolved.get("extras"), dict) else {},
    }
    try:
        reply = await run_ops(job, [op], timeout=timeout)
    except (BrowserBridgeError, VendooCreateError) as exc:
        log.info("No %s category schema: %s", marketplace, exc)
        return {}
    hit = next(
        (r for r in (reply.get("results") or []) if r.get("op") == "category_specifics"), {}
    )
    if not hit.get("ok"):
        log.info("No %s category schema: %s", marketplace, hit.get("error") or "empty reply")
        return {}
    specs = normalize_specifics(hit.get("specifics"))
    save_fields(marketplace, category_id, specs)
    return specs


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


async def resolve_listing_labels(job, listing: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Swap label names for the Vendoo label ids an item actually stores.

    Vendoo's label box renders only ids it finds in the seller's label list, so
    a name sent as-is is saved but never shown. Missing labels are created.
    """
    from vendoo_studio.services import vendoo_label_catalog

    names = [str(n).strip() for n in (listing.get("labels") or []) if str(n).strip()]
    if not names:
        return listing, []
    try:
        reply = await run_ops(job, [{"op": "resolve_labels", "names": names}])
        ids = _result(reply, "resolve_labels").get("ids")
    except (VendooCreateError, BrowserBridgeError) as exc:
        log.warning("Vendoo labels not resolved: %s", exc)
        ids = None
    if not isinstance(ids, list):
        return {**listing, "labels": []}, [{"field": "labels", "value": ", ".join(names)}]
    resolved = [str(i) for i in ids if i]
    # When every input was a display name (not an id) and none were duplicates,
    # ids come back in the same order — learn the map for later Regenerate.
    unique_names: list[str] = []
    seen_names: set[str] = set()
    for name in names:
        if not name or vendoo_label_catalog.looks_like_label_id(name):
            continue
        key = name.casefold()
        if key in seen_names:
            continue
        seen_names.add(key)
        unique_names.append(name)
    if unique_names and len(unique_names) == len(resolved):
        vendoo_label_catalog.remember(dict(zip(resolved, unique_names, strict=True)))
    return {**listing, "labels": resolved}, []


async def label_display_map(job=None, *, timeout: float = REQUEST_TIMEOUT_SEC) -> dict[str, str]:
    """Vendoo label id to seller-facing name.

    Always starts from the on-disk cache so Regenerate can still name chips when
    Chrome is quiet. A live ``list_labels`` (when reachable) refreshes the cache.
    Callers that only decorate a result should pass ``LOOKUP_TIMEOUT_SEC``.
    """
    from types import SimpleNamespace

    from vendoo_studio.services import vendoo_label_catalog

    cached = vendoo_label_catalog.load()
    bridge_job = job if job is not None else SimpleNamespace(id=None)
    try:
        reply = await run_ops(bridge_job, [{"op": "list_labels"}], timeout=timeout)
        catalog = _result(reply, "list_labels").get("labels") or []
    except (VendooCreateError, BrowserBridgeError) as exc:
        log.warning("Vendoo label catalog not loaded: %s", exc)
        return cached
    by_id: dict[str, str] = {}
    if isinstance(catalog, list):
        for row in catalog:
            if not isinstance(row, dict):
                continue
            label_id = str(row.get("id") or "").strip()
            name = str(row.get("name") or "").strip()
            if label_id and name:
                by_id[label_id] = name
    if by_id:
        return vendoo_label_catalog.remember(by_id)
    return cached


def apply_label_display_names(labels: list[Any], names: dict[str, str]) -> list[str]:
    """Map ids to names where the catalog knows them; names pass through."""
    from vendoo_studio.services import vendoo_label_catalog

    return vendoo_label_catalog.apply(labels, names)


async def resolve_label_display_names(
    job, labels: list[Any], *, timeout: float = REQUEST_TIMEOUT_SEC
) -> list[str]:
    """Replace Vendoo label ids with the seller-facing names from their catalog.

    Import and Regenerate carryover otherwise leave opaque Firestore ids in Item
    Details. Names that are already names pass through unchanged. A missing job
    still applies the on-disk cache.
    """
    cleaned = [str(label).strip() for label in (labels or []) if str(label).strip()]
    if not cleaned:
        return cleaned
    return apply_label_display_names(cleaned, await label_display_map(job, timeout=timeout))


def _category_paths(listing: dict[str, Any]) -> dict[str, str]:
    cats = listing.get("marketplace_categories")
    return {
        "general": str(listing.get("category_path") or ""),
        **{key: str((cats or {}).get(key) or "") for key in CATEGORY_MARKETPLACES},
    }


def _invalidate_changed_categories(listing: dict[str, Any]) -> None:
    """A breadcrumb edit must not reuse the leaf ids prepared for its old path."""
    prepared = listing.get("_vendoo_preparation")
    previous = prepared.get("categories") if isinstance(prepared, dict) else None
    if not isinstance(previous, dict):
        return
    paths = _category_paths(listing)
    changed = {key for key, path in paths.items() if previous.get(key) != path}
    if "general" in changed:
        changed.update(CATEGORY_MARKETPLACES)
        listing.pop("category_id", None)
    for key in changed:
        for name in ("marketplace_category_ids", "marketplace_category_objects"):
            if isinstance(listing.get(name), dict):
                listing[name].pop(key, None)
        specifics = listing.get(f"{key}_specifics")
        if isinstance(specifics, dict):
            specifics.pop("categoryId", None)
            specifics.pop("categoryPath", None)


def _field_signature(listing: dict[str, Any], specifics: dict[str, dict[str, FieldSpec]]) -> str:
    """New categories, schemas, gaps or repair rules need another AI fill pass."""
    from vendoo_studio.services.category_fields import listing_category_ids
    from vendoo_studio.services.listing_field_gaps import gap_fill_rules

    payload = {
        "categories": _category_paths(listing),
        "ids": listing_category_ids(listing),
        "schemas": {key: specs_to_rows(fields) for key, fields in specifics.items()},
        "gaps": specifics_gaps(listing, specifics),
        "rules": hashlib.sha256(gap_fill_rules().encode()).hexdigest(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


async def prepare_listing_fields_for_vendoo(
    job,
    listing: dict[str, Any],
    *,
    provider=None,
    evidence: str = "",
    mark=None,
    timeout: float = REQUEST_TIMEOUT_SEC,
) -> tuple[dict[str, Any], dict[str, dict[str, FieldSpec]], dict[str, Any] | None, list[dict[str, str]], list[dict[str, Any]]]:
    """Prepare listing data with reads only; safe to run before seller approval.

    Persist the returned listing during generation. Send and Update then reuse
    its leaf ids and completed fill pass, including fields the evidence could
    not answer. Price/copy edits do not repeat that pass; clearing a field or
    changing its category/schema does.
    """
    listing = copy.deepcopy(listing)
    _invalidate_changed_categories(listing)
    schema = load_schema()
    if mark:
        mark("vendoo_api_categories")
    listing, category_unresolved = await resolve_listing_categories(job, listing, timeout=timeout)
    if mark:
        mark("vendoo_api_specifics")
    specifics = await fetch_listing_specifics(job, listing, timeout=timeout)
    from vendoo_studio.models.ebay_fields import normalize_ebay_sizes

    normalize_ebay_sizes(listing)
    if mark:
        mark("vendoo_api_fields")
    prepared = listing.get("_vendoo_preparation")
    signature = prepared.get("field_signature") if isinstance(prepared, dict) else None
    unfilled = specifics_gaps(listing, specifics)
    if signature != _field_signature(listing, specifics):
        listing, unfilled = await fill_listing_specifics(
            listing, specifics, provider, evidence=evidence
        )
    if provider is not None or not unfilled:
        listing["_vendoo_preparation"] = {
            "categories": _category_paths(listing),
            "field_signature": _field_signature(listing, specifics),
        }
    return listing, specifics, schema, category_unresolved, unfilled


async def prepare_listing_for_vendoo(
    job, listing: dict[str, Any], *, provider=None, evidence: str = "", mark=None,
) -> tuple[dict[str, Any], dict[str, dict[str, FieldSpec]], dict[str, Any] | None, list[dict[str, str]], list[dict[str, Any]]]:
    """Reuse prepared fields and resolve labels only after seller approval."""
    from vendoo_studio.services.vendoo_send import job_repo
    from vendoo_studio.services.vendoo_specifics import specs_from_rows

    repo = job_repo(job)
    event = repo.latest_event(job.id, "vendoo_review") if repo else None
    if event:
        if mark:
            mark("vendoo_api_reviewed")
        reviewed = event.payload
        listing = copy.deepcopy(reviewed["snapshot"])
        specifics = {mp: specs_from_rows(rows) for mp, rows in reviewed["specifics"].items()}
        schema, unresolved, unfilled = reviewed["schema"], reviewed["unresolved"], reviewed["unfilled"]
    else:
        listing, specifics, schema, unresolved, unfilled = await prepare_listing_fields_for_vendoo(
            job, listing, provider=provider, evidence=evidence, mark=mark,
        )
    listing, label_unresolved = await resolve_listing_labels(job, listing)
    return listing, specifics, schema, [*unresolved, *label_unresolved], unfilled


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
    approved_labels = list(listing.get("labels") or [])

    def mark(step: str) -> None:
        from sqlalchemy.orm import object_session

        from vendoo_studio.repositories.queries import JobRepo

        try:
            session = object_session(job)
        except Exception:  # noqa: BLE001 - tests pass a plain namespace
            return
        if session is None:
            return
        JobRepo(session).update_status(job.id, "dispatched", step)
        session.refresh(job)
        status = str(getattr(job, "status", "") or "")
        if status in {"cancelled", "failed"}:
            raise VendooCreateError(
                getattr(job, "last_error", None) or f"Send was {status}"
            )

    previous = pending_send(job)
    # Check the reserved id before doing work. Only an explicit 404 permits
    # another create; an auth, network or server failure leaves it recoverable.
    recovered = None
    recovery_results: list[Any] = []
    if previous:
        recovery = await run_ops(job, [
            {"op": "session", "expected_uid": previous["uid"]},
            {"op": "get_item", "item_id": previous["item_id"], "allow_missing": True, "with_version": True},
        ])
        recovered = _result(recovery, "get_item").get("item")
        recovery_results = recovery["results"]

    with measure_stage(job, "prepare"):
        listing, specifics, schema, category_unresolved, unfilled = await prepare_listing_for_vendoo(
            job, listing, provider=provider, evidence=evidence, mark=mark,
        )

    # Photos and the id first: the item body references both.
    mark("vendoo_api_photos")
    prep_ops = [{"op": "session"}]
    if previous:
        prep_ops[0]["expected_uid"] = previous["uid"]
    else:
        prep_ops.append({"op": "new_item_id"})
    prep = await run_ops(job, [*prep_ops, {"op": "subscription"}, *_photo_ops(job, photos)])
    uid = str(_result(prep, "session").get("uid") or "")
    item_id = str(previous["item_id"] if previous else _result(prep, "new_item_id").get("item_id") or "")
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
    checkpoint(job, uid, item_id)

    mark("vendoo_api_create")
    if recovered is None:
        created = await run_ops(job, [
            {"op": "create_item", "item": item, "subscription_version": subscription_version},
            {"op": "get_item", "item_id": item_id, "with_version": True},
        ])
        stored = _result(created, "get_item").get("item")
    else:
        created = {"results": []}
        stored = recovered
    if not isinstance(stored, dict) or not stored:
        raise VendooCreateError("Vendoo did not return the saved draft; retry Send to recover it.")
    # createItem sometimes drops marketplace fields (Depop style tags, brand
    # overrides, Mercari No Brand). Push only those — not every account default
    # Vendoo filled in after create.
    patch_results: list[Any] = []
    if isinstance(stored, dict):
        fixes = {
            path: value
            for path, value in changed_fields(stored, item).items()
            if path == "labels"
            or path.endswith(".style")
            or path.endswith(".brand")
            or path.endswith(".noBrand")
            or path.endswith(".marketplaceSpecifics.age")
            or path.endswith(".marketplaceSpecifics.source")
            or path.endswith(".marketplaceSpecifics.whoMade")
            or path.endswith(".marketplaceSpecifics.whatIsIt")
            or path.endswith(".marketplaceSpecifics.whenMade")
            or path.endswith(".marketplaceSpecifics.smartSell")
            or path.endswith(".marketplaceSpecifics.smartPricing")
            or path.endswith(".marketplaceSpecifics.floorPrice")
            or path.endswith(".marketplaceSpecifics.shippingLabel")
            or ".marketplaceSpecifics.shipping." in path
            or ".marketplaceSpecifics.pricingFormat" in path
            or ".pricingFormatDetails.fixedPrice." in path
        }
        if recovered is not None:
            # A retry may approve newer copy. Reconcile it onto the same draft
            # instead of making another item. Only Studio's form fields change.
            from vendoo_studio.services.vendoo_api import apply_update_all

            apply_update_all(stored, item, schema=schema)
            fixes = changed_fields(stored, item)
            if (stored.get("generalDetails") or {}).get("images") != images:
                fixes["generalDetails.images"] = images
        if fixes:
            mark("vendoo_api_patch")
            general = {k: v for k, v in fixes.items() if not k.startswith("listings.")}
            forms = {k: v for k, v in fixes.items() if k.startswith("listings.")}
            expected_version = stored.get("_studio_update_time")
            if not expected_version:
                raise VendooCreateError("Reload the Vendoo extension before retrying Send: the draft version is missing.")
            for batch in (general, forms):
                if not batch:
                    continue
                op = {"op": "update_item", "item_id": item_id, "updates": batch}
                op["expected_update_time"] = expected_version
                patched = await run_ops(job, [op])
                patch_results.extend(patched["results"])
                expected_version = _result(patched, "update_item").get("update_time")
                if not expected_version:
                    raise VendooCreateError("Vendoo did not return the draft version. Retry Send to recover it.")
            mark("vendoo_api_verify")
            patched = await run_ops(job, [{"op": "get_item", "item_id": item_id, "raw": True}])
            patch_results.extend(patched["results"])
            stored = _result(patched, "get_item").get("item")
            remaining = diff_updates(fixes, stored if isinstance(stored, dict) else {})
            if remaining:
                raise VendooCreateError(
                    "Vendoo did not retain repaired fields: " + ", ".join(row["field"] for row in remaining),
                    results=patch_results,
                )
    diff = diff_roundtrip(item, stored) if isinstance(stored, dict) else []

    return {
        "prepared_listing": {**listing, "labels": approved_labels},
        "unfilled": unfilled,
        "item_id": item_id,
        "url": f"https://web.vendoo.co/app/item/{item_id}",
        "unresolved": [entry for entry in unresolved],
        "diff": diff,
        "stored": stored if isinstance(stored, dict) else None,
        "results": [*recovery_results, *prep["results"], *created["results"], *patch_results],
    }
