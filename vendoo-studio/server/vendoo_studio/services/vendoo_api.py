"""Build Vendoo items in the exact shape Vendoo's own form produces.

Vendoo's create-item form never fills anything: it builds an item object,
uploads photos through the inventory microservice, mints a Firestore id and
calls the ``items`` Cloud Function with ``{type: "createItem"}``. Studio does the
same (``vendoo_create``), so a generated listing is stored as data with every
marketplace section exactly as computed.

See ``docs/vendoo-listing-architecture.md``. This module is the inverse of
``vendoo_import.listing_from_vendoo`` and mirrors Vendoo's ``getInit*Form``
defaults, which is what makes the result indistinguishable from a form save.

Vendoo's coded vocabularies (condition codes, colour codes) are not guessed.
``observe_item_schema`` learns them from the user's own existing items, and
``build_vendoo_item`` reports any field it could not encode confidently rather
than storing a value that looks right and is wrong.
"""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from typing import Any

log = logging.getLogger("vendoo_studio.vendoo_api")

API_BASE = "https://api.web.vendoo.co"
MSVC_BASE = "https://us.vendoo.co"
FUNCTIONS_BASE = "https://us-central1-vendoo-prod-7948f.cloudfunctions.net"
FIREBASE_PROJECT = "vendoo-prod-7948f"

GET_ITEM = "/api/item/{item_id}"
CATEGORY_SEARCH = "/api/category/search"
IMAGE_UPLOAD_URL = "/inventory/v1/images/url"
ITEMS_FUNCTION = "/items"
# Bulk importer path; takes items that came *from* a marketplace. Kept for
# reference — the form path above is what a net-new item uses.
IMPORT_NORMALIZED = "/api/rest/v1/import/items_normalized"

# Deliberately not wired up: these publish to marketplaces, and AGENTS.md says
# automation stops at saved drafts.
_LIST_ITEM = "/api/item/{item_id}/list"
_DELIST_ITEM = "/api/item/{item_id}/delist"

GENERAL_KEY = "generalDetails"
LISTINGS_KEY = "listings"
DEFAULT_ORIGIN = "vendoo"
CURRENT_ITEM_VERSION = 10

# Every marketplace Vendoo's new-item factory seeds a listings section for.
ALL_MARKETPLACES = (
    "ebay", "etsy", "poshmark", "mercari", "grailed", "depop", "tradesy", "kidizen",
    "facebook", "shopify", "sellhound", "vestiaire", "vinted", "whatnot", "sellwild", "vestiaireApi",
)

# generalDetails fields Vendoo stores as a coded object with a display label.
CODED_FIELDS = ("condition", "primaryColor", "secondaryColor")

_LABEL_KEYS = ("displayName", "label", "name")
_VALUE_KEYS = ("value", "id", "key", "code")

_PACKAGE_DIMS_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*$", re.I
)

SPECIFICS_SOURCES = {mp: f"{mp}_specifics" for mp in ("ebay", "poshmark", "mercari", "depop", "etsy")}

# Keys in <marketplace>_specifics that Studio keeps for itself, not Vendoo.
_STUDIO_ONLY_SPECIFIC_KEYS = frozenset({"categoryPath", "category_specifics", "size", "sizeType"})

# Studio names a few Etsy fields differently from Vendoo.
ETSY_KEY_MAP = {"who_made": "whoMade", "what_is": "whatIsIt", "when_made": "whenMade"}


# --------------------------------------------------------------------------
# Vendoo's defaults (mirrors getInitGeneralDetails / getInit*Form)
# --------------------------------------------------------------------------


def _weight_dims_overrides() -> dict[str, Any]:
    return {
        "quantity": "1",
        "weight": {"pounds": "0", "ounces": "0"},
        "dimensions": {"length": "0", "width": "0", "height": "0"},
    }


def default_general_details() -> dict[str, Any]:
    return {
        "images": [],
        "videos": [],
        "title": "",
        "description": "",
        "notes": "",
        "brand": "",
        "condition": "",
        "primaryColor": "",
        "secondaryColor": "",
        "sku": "",
        "category": "",
        "weight": {"pounds": "0", "ounces": "0"},
        "dimensions": {"length": "0", "width": "0", "height": "0"},
        "price": "",
        "cost": "",
        "tags": [],
        "quantity": "1",
        "size": {"option": {"label": "", "value": ""}, "scale": {"label": "", "value": ""}},
    }


def _marketplace_specific_defaults(marketplace: str) -> dict[str, Any]:
    if marketplace == "ebay":
        return {
            "shippingPolicyId": "", "paymentPolicyId": "", "returnsPolicyId": "",
            "returnPayedBy": "", "returnWithin": "", "returnRefundMethod": "",
            "shippingService": "", "statusItem": "Active",
            "shipping": {"cost": "", "method": "Standard", "location": "", "handling": "", "type": ""},
            "paymentMethod": "PayPal", "conditionDescription": "", "paypalEmail": "",
            "acceptReturns": "", "pricingFormat": "FixedPriceItem",
            "pricingFormatDetails": {
                "auction": {"duration": "Days_7", "startingPrice": "", "buyItNowPrice": "",
                            "allowBestOffer": "", "acceptOffersOfAtLeast": "", "declineOffersLowerThan": ""},
                "fixedPrice": {"duration": "GTC", "buyItNowPrice": "", "allowBestOffer": "",
                               "acceptOffersOfAtLeast": "", "declineOffersLowerThan": ""},
            },
        }
    if marketplace == "etsy":
        return {
            "listingState": None, "renewalOption": None, "quantity": 1,
            "shippingTemplateID": "", "processingProfileID": "", "tags": [],
            "whoMade": "i_did", "isSupply": True, "whenMade": "2020_2025", "whatIsIt": "finished_product",
            "returnPolicyID": None, "materials": [], "listingType": "",
        }
    if marketplace == "poshmark":
        return {"originalPrice": ""}
    if marketplace == "mercari":
        return {
            "tags": [], "smartPricing": False, "floorPrice": "",
            "shipping": {"deliveryMethod": "", "location": ""}, "mercariLocalInformation": "",
        }
    if marketplace == "depop":
        return {
            "priceCurrency": "USD", "shippingMethods": [], "shippingMethod": "", "nationalShippingCost": "",
            "age": [], "source": [], "style": [],
            "location": {"geoLat": 0, "geoLng": 0, "address": "", "countryCode": "", "id": "", "zipCode": ""},
        }
    return {}


def default_listing_section(marketplace: str) -> dict[str, Any]:
    """One ``listings.<marketplace>`` entry as Vendoo's factory seeds it."""
    section: dict[str, Any] = {
        "marketplaceID": marketplace,
        "dateCreated": "",
        "dateLastModified": "",
        "type": "listing",
        "status": {"notListed": True},
        "overrides": _weight_dims_overrides() if marketplace in ("ebay", "etsy", "poshmark", "mercari") else (
            {"quantity": "1"} if marketplace == "depop" else {}
        ),
        "categorySpecifics": {},
        "listingAttemptMessages": [],
        "marketplaceSpecifics": _marketplace_specific_defaults(marketplace),
        "sales": [],
    }
    if marketplace in ("shopify", "sellhound", "sellwild", "whatnot"):
        section["listedID"] = ""
        section["listingURL"] = ""
    return section


# --------------------------------------------------------------------------
# Learning Vendoo's encodings from the user's own items
# --------------------------------------------------------------------------


def _norm(text: Any) -> str:
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

    ``{"fields": {name: {"labels": {normalised label: code}, "codes": [...],
    "shape": "object"|"scalar"}}, "item_count": n}``. Anything unseen is
    reported by the serializer instead of being invented.
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


def encode_field(schema: dict[str, Any] | None, name: str, label: str | None) -> tuple[Any, bool]:
    """Encode a human label into Vendoo's stored value.

    Returns ``(value, resolved)``; ``resolved`` is False when nothing learned
    covers this label, so the caller can report it instead of guessing.
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


def _num_str(value: Any) -> str:
    """Vendoo's form stores numbers as strings ("48", "0")."""
    if value in (None, ""):
        return ""
    try:
        number = float(str(value).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return str(value)
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _dimensions(raw: Any) -> dict[str, str] | None:
    match = _PACKAGE_DIMS_RE.match(str(raw or ""))
    if not match:
        return None
    length, width, height = match.groups()
    return {"length": _num_str(length), "width": _num_str(width), "height": _num_str(height)}


def _category(listing: dict[str, Any]) -> Any:
    """Prefer a resolved Vendoo category object; fall back to the display path."""
    category_id = _clean(listing.get("category_id"))
    path = _clean(listing.get("category_path"))
    parts = [part.strip() for part in str(path or "").split(">") if part.strip()]
    if category_id:
        return {"id": category_id, "displayPath": parts}
    return path


def _size(listing: dict[str, Any]) -> dict[str, Any] | None:
    size = _clean(listing.get("size")) or _clean(listing.get("size_us"))
    scale = _clean(listing.get("sizeType"))
    if not size and not scale:
        return None
    return {
        "option": {"label": size or "", "value": size or ""},
        "scale": {"label": scale or "", "value": scale or ""},
    }


def _general_details(
    listing: dict[str, Any],
    schema: dict[str, Any] | None,
    images: list[Any],
    unresolved: list[dict[str, str]],
) -> dict[str, Any]:
    general = default_general_details()

    def coded(name: str, label: Any) -> Any:
        value, ok = encode_field(schema, name, _clean(label))
        if not ok:
            unresolved.append({"field": name, "value": str(label)})
        return value if value is not None else ""

    general.update({
        "images": [{"url": img} if isinstance(img, str) else img for img in images],
        "title": _clean(listing.get("title")) or "",
        "description": _clean(listing.get("description")) or "",
        "notes": _clean(listing.get("internal_notes")) or "",
        "brand": _clean(listing.get("brand")) or "",
        "sku": _clean(listing.get("sku")) or "",
        "price": _num_str(listing.get("price")),
        "cost": _num_str(listing.get("cost")),
        "quantity": _num_str(listing.get("quantity") or 1),
        "tags": _string_list(listing.get("tags")),
        "condition": coded("condition", listing.get("condition")),
        "primaryColor": coded("primaryColor", listing.get("primaryColor")),
        "secondaryColor": coded("secondaryColor", listing.get("secondaryColor")),
    })
    category = _category(listing)
    if isinstance(category, dict):
        general["categoryV2"] = category
    elif category:
        general["category"] = category
    size = _size(listing)
    if size:
        general["size"] = size
    weight_lb, weight_oz = listing.get("weight_lb"), listing.get("weight_oz")
    if weight_lb not in (None, "") or weight_oz not in (None, ""):
        general["weight"] = {"pounds": _num_str(weight_lb or 0), "ounces": _num_str(weight_oz or 0)}
    dims = _dimensions(listing.get("package_dimensions_in"))
    if dims:
        general["dimensions"] = dims
    return general


def _listing_section(marketplace: str, listing: dict[str, Any], general: dict[str, Any]) -> dict[str, Any]:
    """Fill one marketplace section from ``<marketplace>_specifics``.

    Known marketplaceSpecifics keys land there; a Vendoo category path becomes
    the section's ``overrides.categoryV2``; everything else is a category
    specific (item specifics, size scales), which is where Vendoo keeps
    per-category form values and where ``vendoo_import`` reads them back from.
    """
    section = default_listing_section(marketplace)
    raw = listing.get(SPECIFICS_SOURCES.get(marketplace, f"{marketplace}_specifics"))
    specifics = dict(raw) if isinstance(raw, dict) else {}
    known = section["marketplaceSpecifics"]

    for key in ("weight", "dimensions"):
        if key in section["overrides"] and general.get(key):
            section["overrides"][key] = deepcopy(general[key])
    if "quantity" in section["overrides"]:
        section["overrides"]["quantity"] = general.get("quantity") or "1"

    path = specifics.pop("categoryPath", None)
    parts = [str(p).strip() for p in path if str(p or "").strip()] if isinstance(path, list) else []
    if parts:
        section["overrides"]["categoryV2"] = {"displayPath": parts}

    nested = specifics.pop("category_specifics", None)
    if isinstance(nested, dict):
        section["categorySpecifics"].update({k: v for k, v in nested.items() if v not in (None, "")})

    for key, value in specifics.items():
        if value in (None, "", []) or key in _STUDIO_ONLY_SPECIFIC_KEYS:
            continue
        dest = ETSY_KEY_MAP.get(key, key) if marketplace == "etsy" else key
        if dest in known:
            if isinstance(known[dest], dict) and isinstance(value, dict):
                known[dest] = {**known[dest], **value}
            elif isinstance(known[dest], list):
                known[dest] = _string_list(value)
            elif dest == "originalPrice":
                known[dest] = _num_str(value)
            else:
                known[dest] = value
        else:
            section["categorySpecifics"][dest] = value
    return section


def build_vendoo_item(
    listing: dict[str, Any],
    schema: dict[str, Any] | None = None,
    *,
    images: list[Any] | None = None,
    user_id: str = "",
    item_id: str = "",
    origin: str = DEFAULT_ORIGIN,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """A complete Vendoo item, shaped exactly like a form save.

    ``images`` are the ``{version: 3, id, originalMaxDimension}`` objects the
    inventory upload returns. Returns ``(item, unresolved)``; ``unresolved``
    names every coded field sent as plain text because nothing learned covered
    it — show those to the seller rather than assuming they landed.
    """
    unresolved: list[dict[str, str]] = []
    general = _general_details(listing, schema, images or [], unresolved)
    listings = {mp: _listing_section(mp, listing, general) for mp in ALL_MARKETPLACES}
    item = {
        "origin": origin,
        "version": CURRENT_ITEM_VERSION,
        "status": {"notSaved": True},
        "type": "item",
        "userID": user_id,
        "itemID": item_id,
        "labels": _string_list(listing.get("labels")),
        GENERAL_KEY: general,
        LISTINGS_KEY: listings,
    }
    return item, unresolved


def create_item_payload(item: dict[str, Any], subscription_version: str | None) -> dict[str, Any]:
    """Body for the ``items`` Cloud Function (callable envelope added by the extension)."""
    return {"type": "createItem", "payload": {"item": item, "subscriptionVersion": subscription_version}}


# --------------------------------------------------------------------------
# Round-trip verification
# --------------------------------------------------------------------------


def _comparable(value: Any) -> Any:
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
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return _norm(value)
    return value


def diff_roundtrip(sent: dict[str, Any], stored: dict[str, Any]) -> list[dict[str, Any]]:
    """Fields Vendoo stored differently from what we sent (generalDetails only).

    Only values we actually set are compared; Vendoo defaults everything else.
    """
    sent_general = sent.get(GENERAL_KEY) or {}
    stored_general = stored.get(GENERAL_KEY) or {}
    defaults = default_general_details()
    out: list[dict[str, Any]] = []
    for key, value in sent_general.items():
        # Blanks and untouched form defaults are Vendoo's to fill in, not ours to check.
        if value in ("", [], None) or key == "images" or value == defaults.get(key):
            continue
        want, got = _comparable(value), _comparable(stored_general.get(key))
        if want != got:
            out.append({"field": key, "sent": value, "stored": stored_general.get(key)})
    return out
