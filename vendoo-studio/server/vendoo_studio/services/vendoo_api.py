"""Write listings through Vendoo's own REST API instead of filling its form.

Vendoo's web app talks to ``api.web.vendoo.co`` over a conventional REST API,
authenticated by the Firebase session cookie a signed-in browser already holds.
Posting an item there is exact: the values we computed are the values stored, so
category selection and dropdown matching stop being fuzzy-match problems.

See ``docs/vendoo-listing-architecture.md``. This module is the inverse of
``vendoo_import.listing_from_vendoo`` — that reads Vendoo items into Studio's
listing shape, this writes Studio listings back out.

Vendoo's encodings (condition codes, category objects, colour codes) are not
guessed here. ``observe_item_schema`` learns them from the user's own existing
items, and ``vendoo_item_from_listing`` reports any field it could not encode
confidently rather than sending a value that would silently store wrong.
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger("vendoo_studio.vendoo_api")

API_BASE = "https://api.web.vendoo.co"

# Endpoints observed in the web.vendoo.co bundle. Kept together so a change in
# Vendoo's API is one edit, not a hunt through call sites.
GET_ITEM = "/api/item/{item_id}"
IMPORT_NORMALIZED = "/api/rest/v1/import/items_normalized"
CATEGORY_SEARCH = "/api/category/search"
SIZE_QUERY = "/api/rest/v1/size/query"
# Takes {"images": [url, ...]} and returns Vendoo-hosted image objects. Vendoo's
# own importer runs every image through this before posting an item, so the
# stored item never points at a marketplace CDN.
STATIC_UPLOAD = "/api/static/upload"

# Deliberately not wired up: these publish to marketplaces, and AGENTS.md says
# automation stops at saved drafts. Listed so nobody re-derives them by accident.
_LIST_ITEM = "/api/item/{item_id}/list"
_DELIST_ITEM = "/api/item/{item_id}/delist"

GENERAL_KEY = "generalDetails"
LISTINGS_KEY = "listings"

# Vendoo's new-item factory defaults to origin "vendoo" for an item created in
# the app rather than imported from a marketplace, and stamps the item version.
# "vendoo" is not in Vendoo's MARKETPLACES list, so an import call may reject it
# — see the open question in docs/vendoo-listing-architecture.md.
DEFAULT_ORIGIN = "vendoo"
CURRENT_ITEM_VERSION = 10

# generalDetails fields that carry a coded value plus a human label, e.g.
# {"value": "v_pre_owned_good", "displayName": "Pre-Owned - Good"}.
CODED_FIELDS = ("condition", "primaryColor", "secondaryColor", "sizeType")

_LABEL_KEYS = ("displayName", "label", "name")
_VALUE_KEYS = ("value", "id", "key", "code")

SPECIFICS_SOURCES = {
    "ebay": "ebay_specifics",
    "poshmark": "poshmark_specifics",
    "mercari": "mercari_specifics",
    "depop": "depop_specifics",
    "etsy": "etsy_specifics",
}

_PACKAGE_DIMS_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*$", re.I
)


# --------------------------------------------------------------------------
# Learning Vendoo's encodings from the user's own items
# --------------------------------------------------------------------------


def _norm(text: Any) -> str:
    """Fold a label so 'Pre-Owned - Good' and 'pre owned good' match."""
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _label_of(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in _LABEL_KEYS:
        text = value.get(key)
        if isinstance(text, str) and text.strip():
            return text.strip()
    return None


def _code_of(value: Any) -> Any:
    if not isinstance(value, dict):
        return None
    for key in _VALUE_KEYS:
        if value.get(key) not in (None, ""):
            return value[key]
    return None


def observe_item_schema(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Build an encoding table from real Vendoo items.

    Returns ``{"fields": {name: {"labels": {normalised label: code},
    "codes": [...], "shape": "object"|"scalar"}}, "item_count": n}``.

    Every coded field Vendoo returns as an object teaches us one label→code
    pair. Probing a handful of varied items covers the common vocabulary;
    anything unseen is reported by the serializer instead of being invented.
    """
    fields: dict[str, dict[str, Any]] = {}

    def record(name: str, raw: Any) -> None:
        entry = fields.setdefault(name, {"labels": {}, "codes": [], "shape": "scalar"})
        if isinstance(raw, list):
            for part in raw:
                record(name, part)
            return
        if isinstance(raw, dict):
            entry["shape"] = "object"
            label, code = _label_of(raw), _code_of(raw)
            if label and code not in (None, ""):
                entry["labels"][_norm(label)] = code
            if code not in (None, "") and code not in entry["codes"]:
                entry["codes"].append(code)
            return
        if raw not in (None, "") and raw not in entry["codes"]:
            entry["codes"].append(raw)
            # A bare code like "v_pre_owned_good" still teaches its own label.
            if isinstance(raw, str) and raw.startswith("v_"):
                entry["labels"].setdefault(_norm(raw[2:]), raw)

    counted = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        counted += 1
        general = item.get(GENERAL_KEY)
        if not isinstance(general, dict):
            continue
        for name, raw in general.items():
            if raw in (None, ""):
                continue
            record(name, raw)

    return {"fields": fields, "item_count": counted}


def encode_field(
    schema: dict[str, Any] | None, name: str, label: str | None
) -> tuple[Any, bool]:
    """Encode a human label into Vendoo's stored value.

    Returns ``(value, resolved)``. ``resolved`` is False when the schema has
    never seen this label — the caller decides whether to send the raw text or
    leave the field out and tell the user.
    """
    if label in (None, ""):
        return None, True
    entry = ((schema or {}).get("fields") or {}).get(name) or {}
    labels: dict[str, Any] = entry.get("labels") or {}
    key = _norm(label)
    if key in labels:
        code = labels[key]
        if entry.get("shape") == "object":
            return {"value": code, "displayName": label}, True
        return code, True
    # Vendoo already stores it verbatim (brand, sku, free text) — not a guess.
    if label in (entry.get("codes") or []):
        return label, True
    return label, False


# --------------------------------------------------------------------------
# Studio listing -> Vendoo item
# --------------------------------------------------------------------------


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return value


def _string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part or "").strip()]
    return [str(value).strip()]


def _dimensions(raw: Any) -> dict[str, float] | None:
    match = _PACKAGE_DIMS_RE.match(str(raw or ""))
    if not match:
        return None
    length, width, height = (float(part) for part in match.groups())
    return {"length": length, "width": width, "height": height}


def _category(listing: dict[str, Any]) -> Any:
    """Prefer a resolved Vendoo category object over a display path string.

    ``category_id`` is what ``/api/category/search`` returns for a leaf; the
    path alone is a display string and Vendoo may not match it.
    """
    category_id = _clean(listing.get("category_id"))
    path = _clean(listing.get("category_path"))
    if category_id:
        out: dict[str, Any] = {"id": category_id}
        if path:
            out["displayPath"] = [part.strip() for part in str(path).split(">") if part.strip()]
        return out
    return path


def vendoo_item_from_listing(
    listing: dict[str, Any],
    schema: dict[str, Any] | None = None,
    *,
    images: list[Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Convert a Studio listing into a Vendoo item body.

    ``images`` belongs under ``generalDetails``, matching Vendoo's own importer,
    and should already be the objects returned by :data:`STATIC_UPLOAD` — plain
    URLs are accepted but leave the item pointing at storage Vendoo does not own.

    Returns ``(item, unresolved)``. ``unresolved`` names every field sent as raw
    text because the observed schema had no encoding for it — surface these
    rather than assuming they landed.
    """
    unresolved: list[dict[str, str]] = []

    def coded(name: str, label: Any) -> Any:
        value, ok = encode_field(schema, name, _clean(label))
        if not ok:
            unresolved.append({"field": name, "value": str(label)})
        return value

    general: dict[str, Any] = {
        "title": _clean(listing.get("title")),
        "description": _clean(listing.get("description")),
        "price": listing.get("price"),
        "cost": listing.get("cost"),
        "quantity": listing.get("quantity") or 1,
        "brand": _clean(listing.get("brand")),
        "sku": _clean(listing.get("sku")),
        "notes": _clean(listing.get("internal_notes")),
        "condition": coded("condition", listing.get("condition")),
        "primaryColor": coded("primaryColor", listing.get("primaryColor")),
        "secondaryColor": coded("secondaryColor", listing.get("secondaryColor")),
        "categoryV2": _category(listing),
        "tags": _string_list(listing.get("tags")),
    }

    size = _clean(listing.get("size")) or _clean(listing.get("size_us"))
    size_type = _clean(listing.get("sizeType"))
    if size:
        general["size"] = {"option": size, "scale": size_type} if size_type else {"option": size}
    if size_type:
        general["sizeType"] = coded("sizeType", size_type)

    weight_lb = listing.get("weight_lb")
    weight_oz = listing.get("weight_oz")
    if weight_lb is not None or weight_oz is not None:
        general["weight"] = {"pounds": int(weight_lb or 0), "ounces": int(weight_oz or 0)}

    dims = _dimensions(listing.get("package_dimensions_in"))
    if dims:
        general["dimensions"] = dims

    listings: dict[str, Any] = {}
    for marketplace, source_key in SPECIFICS_SOURCES.items():
        specifics = listing.get(source_key)
        if isinstance(specifics, dict) and specifics:
            listings[marketplace] = {
                key: value for key, value in specifics.items() if value not in (None, "")
            }

    if images:
        general["images"] = [
            {"url": entry} if isinstance(entry, str) else entry for entry in images
        ]

    item: dict[str, Any] = {
        GENERAL_KEY: {key: value for key, value in general.items() if value not in (None, "", [])},
    }
    if listings:
        item[LISTINGS_KEY] = listings
    # Vendoo keeps labels on the item, not inside generalDetails.
    labels = _string_list(listing.get("labels"))
    if labels:
        item["labels"] = labels

    return item, unresolved


def wrap_item(
    item: dict[str, Any],
    *,
    user_id: str = "",
    item_id: str = "",
    origin: str = DEFAULT_ORIGIN,
) -> dict[str, Any]:
    """Add the envelope Vendoo's own new-item factory puts around an item.

    Vendoo builds a fresh item as
    ``{origin, version, status: {notSaved: true}, type: "item", userID, itemID,
    labels, generalDetails, listings}``. Bare ``generalDetails`` is what the
    import endpoint takes; this is the shape the app itself creates.
    """
    return {
        "origin": origin,
        "version": CURRENT_ITEM_VERSION,
        "status": {"notSaved": True},
        "type": "item",
        "userID": user_id,
        "itemID": item_id,
        "labels": item.get("labels", []),
        GENERAL_KEY: item.get(GENERAL_KEY, {}),
        LISTINGS_KEY: item.get(LISTINGS_KEY, {}),
    }


def import_payload(
    items: list[dict[str, Any]], *, marketplace_user_id: str, marketplace_id: str = "vendoo"
) -> dict[str, Any]:
    """Body for ``POST /api/rest/v1/import/items_normalized``."""
    return {
        "marketplaceId": marketplace_id,
        "marketplaceUserId": marketplace_user_id,
        "items": items,
    }


# --------------------------------------------------------------------------
# Round-trip verification
# --------------------------------------------------------------------------


def _comparable(value: Any) -> Any:
    """Reduce a value to what we can meaningfully compare across the round trip."""
    if isinstance(value, dict):
        label = _label_of(value)
        if label:
            return _norm(label)
        code = _code_of(value)
        if code is not None:
            return _norm(code)
        return {key: _comparable(part) for key, part in sorted(value.items())}
    if isinstance(value, list):
        return [_comparable(part) for part in value]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return _norm(value) if isinstance(value, str) else value


def diff_roundtrip(sent: dict[str, Any], stored: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare what we posted against what Vendoo stored.

    This is the check the form-filling path could never give us: proof that the
    values we computed are the values Vendoo holds. Only fields we actually sent
    are compared — Vendoo defaults everything else.
    """
    sent_general = sent.get(GENERAL_KEY) or {}
    stored_general = stored.get(GENERAL_KEY) or {}
    out: list[dict[str, Any]] = []
    for key, value in sent_general.items():
        want, got = _comparable(value), _comparable(stored_general.get(key))
        if want != got:
            out.append({"field": key, "sent": value, "stored": stored_general.get(key)})
    return out
