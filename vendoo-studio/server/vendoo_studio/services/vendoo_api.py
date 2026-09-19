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

import json
import logging
import re
from copy import deepcopy
from typing import Any

from vendoo_studio.services.vendoo_specifics import (
    FieldSpec,
    encode_scaled,
    encode_specific,
    missing_required,
    scale_key,
    specifics_key,
)

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

# Vendoo's own colour vocabulary, as its app ships it. Learning these from the
# seller's items only ever covers colours they have already used, which is how
# a beige top was stored as the word "Beige" next to a correctly coded
# "v_Pink". Real items confirm the encoding: v_Silver, v_Black.
GENERAL_COLORS: dict[str, str] = {
    "beige": "v_Beige", "black": "v_Black", "blue": "v_Blue", "brown": "v_Brown",
    "cream": "v_Cream", "gold": "v_Gold", "gray": "v_Gray", "grey": "v_Gray",
    "green": "v_Green", "multicolor": "v_Multicolor", "multicolour": "v_Multicolor",
    "orange": "v_Orange", "pink": "v_Pink", "purple": "v_Purple", "red": "v_Red",
    "silver": "v_Silver", "tan": "v_Tan", "white": "v_White", "yellow": "v_Yellow",
}

_LABEL_KEYS = ("displayName", "label", "name")
_VALUE_KEYS = ("value", "id", "key", "code")

_PACKAGE_DIMS_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*$", re.I
)

# USPS Ground Advantage, as Vendoo recorded it on this seller's listed items.
MERCARI_GROUND_ADVANTAGE_CARRIER = "2509"

SPECIFICS_SOURCES = {mp: f"{mp}_specifics" for mp in ("ebay", "poshmark", "mercari", "depop", "etsy")}

# Keys in <marketplace>_specifics that Studio keeps for itself, not Vendoo.
_STUDIO_ONLY_SPECIFIC_KEYS = frozenset({"categoryPath", "category_specifics", "size", "sizeType"})

# Marketplace form brand fields live on overrides, not categorySpecifics. The
# Chrome filler writes `#listings.<mp>.overrides.brand`; create must too.
_BRAND_OVERRIDE_MARKETPLACES = frozenset({"ebay", "etsy", "poshmark", "mercari", "depop"})

# Values that mean "there is no brand" on Mercari — check No Brand/Not sure.
_MERCARI_NO_BRAND_TOKENS = frozenset({
    "", "unbranded", "no brand", "not sure", "no brand not sure", "no brand/not sure",
    "none", "n a", "na", "unknown",
})

# Studio names a few Etsy fields differently from Vendoo.
ETSY_KEY_MAP = {"who_made": "whoMade", "what_is": "whatIsIt", "when_made": "whenMade"}

# Studio names its listing fields in camelCase; Vendoo names the same fields
# per category ("Sleeve Length", "Country of Origin"). Matching is done on the
# words rather than a hand-kept table, so a category Studio has never seen
# still lines up. See ``vendoo_specifics`` for where the field list comes from.
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

# Keys Studio keeps in <marketplace>_specifics that are never category fields.
_NOT_CATEGORY_FIELDS = frozenset({
    "categorypath", "categoryid", "category specifics", "condition description",
    "conditiondescription", "vendoo internal notes", "vendoo labels", "labels",
    # Condition is encoded from the item's own condition against the leaf's
    # option list, not from whatever text sits in <marketplace>_specifics.
    "condition",
})

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
            # Taken from an item this seller actually listed. "i_did" is wrong
            # for resale — Etsy asks who made it, and it was not the seller —
            # and Vendoo stores whatIsIt coded rather than as a word.
            "whoMade": "someone_else", "isSupply": True, "whenMade": "2020_2026", "whatIsIt": "0",
            "returnPolicyID": None, "materials": [], "listingType": "",
        }
    if marketplace == "poshmark":
        return {"originalPrice": ""}
    if marketplace == "mercari":
        return {
            "tags": [], "smartPricing": False, "floorPrice": "",
            # Mercari's prepaid label, which is what every listing here uses.
            # payerId 1 is the seller paying; carrierId is the one a listed
            # item of this seller's carries.
            "shipping": {
                "deliveryMethod": "mercari_shipping", "location": "",
                "payerId": 1, "carrierId": MERCARI_GROUND_ADVANTAGE_CARRIER,
            },
            "mercariLocalInformation": "",
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

    marketplaces: dict[str, dict[str, Any]] = {}
    aspects: dict[str, dict[str, str]] = {}

    counted = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        counted += 1
        general = item.get(GENERAL_KEY)
        if isinstance(general, dict):
            for name, raw in general.items():
                if raw in (None, ""):
                    continue
                record(name, raw)
        observe_listing_encodings(item, marketplaces, aspects)

    return {"fields": fields, "marketplaces": marketplaces, "aspects": aspects, "item_count": counted}


def aspect_suffix(key: str, category_id: Any = "") -> str:
    """``53159_Season`` -> ``Season``. The prefix is the leaf's own id.

    Slug ids contain underscores themselves, so the id is stripped literally
    when known and only a numeric prefix is guessed when it is not.
    """
    text = str(key or "")
    prefix = str(category_id or "")
    if prefix and text.startswith(f"{prefix}_"):
        return text[len(prefix) + 1:]
    return re.sub(r"^\d+_", "", text)


def observe_listing_encodings(
    item: dict[str, Any],
    marketplaces: dict[str, dict[str, Any]],
    aspects: dict[str, dict[str, str]],
) -> None:
    """Learn each marketplace's own vocabulary from one stored item.

    Every marketplace codes condition differently (eBay ``"3000"``, Poshmark
    ``"ug"``, Depop ``"used_good"``) against the same Vendoo ``v_`` code, and
    eBay stores multi-select aspects as lists. Both are read off the seller's
    own items rather than guessed.
    """
    general = item.get(GENERAL_KEY) if isinstance(item.get(GENERAL_KEY), dict) else {}
    general_condition = _code_of(general.get("condition")) or general.get("condition")
    general_key = _norm(general_condition)
    listings = item.get(LISTINGS_KEY)
    if not isinstance(listings, dict):
        return
    for marketplace, section in listings.items():
        if not isinstance(section, dict):
            continue
        overrides = section.get("overrides") if isinstance(section.get("overrides"), dict) else {}
        code = overrides.get("condition")
        if general_key and code not in (None, ""):
            entry = marketplaces.setdefault(str(marketplace), {})
            entry.setdefault("condition", {})[general_key] = code
        specifics = section.get("categorySpecifics")
        if not isinstance(specifics, dict):
            continue
        leaf = overrides.get("categoryV2") if isinstance(overrides.get("categoryV2"), dict) else {}
        leaf_id = leaf.get("id") or ""
        shapes = aspects.setdefault(str(marketplace), {})
        for key, value in specifics.items():
            suffix = aspect_suffix(key, leaf_id)
            if not suffix:
                continue
            # A filled list proves multi-select; an empty value proves nothing.
            if isinstance(value, list):
                shapes[suffix] = "list"
            elif value not in (None, "") and suffix not in shapes:
                shapes[suffix] = "scalar"


def marketplace_condition(schema: dict[str, Any] | None, marketplace: str, general_condition: Any) -> Any:
    """The marketplace's own condition code for a Vendoo condition, or None.

    None means nothing learned covers it. Writing a Vendoo label into
    ``listings.<marketplace>.overrides.condition`` instead is what breaks
    eBay's form once a category leaf is chosen.
    """
    if general_condition in (None, ""):
        return None
    table = (((schema or {}).get("marketplaces") or {}).get(marketplace) or {}).get("condition") or {}
    return table.get(_norm(general_condition))


def aspect_is_multi(schema: dict[str, Any] | None, marketplace: str, suffix: str) -> bool:
    """Whether this marketplace stores that aspect as a list."""
    shapes = ((schema or {}).get("aspects") or {}).get(marketplace) or {}
    return shapes.get(suffix) == "list"


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
    # Vendoo's general vocabulary is coarser than Studio's: one ``v_preowned``
    # covers Pre-Owned Excellent/Good/Fair. Match on the squashed text so the
    # tier Studio adds still lands on the code the seller's items use.
    squashed = key.replace(" ", "")
    for learned, code in labels.items():
        target = learned.replace(" ", "")
        if target and (squashed.startswith(target) or target.startswith(squashed)):
            if entry.get("shape") == "object":
                return {"value": code, "displayName": label}, True
            return code, True
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


def _listing_brand(listing: dict[str, Any], marketplace: str) -> str:
    """Brand for one marketplace form: specifics override, else general brand."""
    raw = listing.get(SPECIFICS_SOURCES.get(marketplace, f"{marketplace}_specifics"))
    if isinstance(raw, dict):
        specific = _clean(raw.get("brand"))
        if specific:
            return specific
    return _clean(listing.get("brand")) or ""


def _ebay_brand_label(brand: str) -> str:
    """eBay's Brand dropdown matches ``Unbranded``, not a lowercased free-text."""
    text = _clean(brand) or ""
    if _norm(text) == "unbranded":
        return "Unbranded"
    return text


def _mercari_wants_no_brand(brand: str) -> bool:
    return _norm(brand) in _MERCARI_NO_BRAND_TOKENS


def _apply_marketplace_brand(
    section: dict[str, Any],
    marketplace: str,
    listing: dict[str, Any],
) -> None:
    """Put brand where Vendoo's forms actually read it — ``overrides.brand``.

    Mercari has no catch-all brand option: an empty or unlisted brand is the
    No Brand/Not sure checkbox (``overrides.noBrand``), not a typed value.
    Depop's catch-all is the ``Other`` option.
    """
    if marketplace not in _BRAND_OVERRIDE_MARKETPLACES:
        return
    brand = _listing_brand(listing, marketplace)
    overrides = section.setdefault("overrides", {})
    if marketplace == "mercari":
        if _mercari_wants_no_brand(brand):
            overrides["noBrand"] = True
            overrides.pop("brand", None)
        elif brand:
            overrides["brand"] = brand
            overrides["noBrand"] = False
        return
    if marketplace == "depop" and _mercari_wants_no_brand(brand):
        overrides["brand"] = "Other"
        return
    if not brand:
        return
    if marketplace == "ebay":
        brand = _ebay_brand_label(brand)
    overrides["brand"] = brand


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


def path_parts(path: Any) -> list[str]:
    """Split a Vendoo breadcrumb (string or list) into displayPath parts."""
    if isinstance(path, list):
        return [str(part).strip() for part in path if str(part or "").strip()]
    text = str(path or "").strip()
    if not text:
        return []
    return [part.strip() for part in text.split(">") if part.strip()]


def category_v2(category_id: Any = None, path: Any = None) -> dict[str, Any] | None:
    """Build the ``categoryV2`` object Vendoo's form stores when a tree leaf is chosen."""
    parts = path_parts(path)
    cat_id = _clean(category_id)
    if not cat_id and not parts:
        return None
    out: dict[str, Any] = {}
    if cat_id:
        out["id"] = cat_id
    if parts:
        out["displayPath"] = parts
    return out or None


def pick_category_hit(matches: list[Any] | None, wanted_path: str) -> dict[str, Any] | None:
    """Choose the search hit that best matches the Studio breadcrumb."""
    wanted_parts = path_parts(wanted_path)
    wanted_norm = _norm(" > ".join(wanted_parts))
    pool = [m for m in (matches or []) if isinstance(m, dict)]
    if not pool:
        return None

    def hit_parts(hit: dict[str, Any]) -> list[str]:
        return hit_display_path(hit)

    leaves = [m for m in pool if m.get("is_leaf") is True]
    candidates = leaves or pool
    for hit in candidates:
        parts = hit_parts(hit)
        if parts and _norm(" > ".join(parts)) == wanted_norm:
            return hit
    if wanted_parts:
        leaf = _norm(wanted_parts[-1])
        for hit in candidates:
            parts = hit_parts(hit)
            if parts and _norm(parts[-1]) == leaf:
                return hit
    return candidates[0]


def hit_display_path(hit: dict[str, Any]) -> list[str]:
    """Breadcrumb parts from a search hit, whichever key carries them."""
    for key in ("all_category_label", "displayPath", "display_path", "searchable_text", "path", "text"):
        parts = path_parts(hit.get(key))
        if parts:
            return parts
    return []


def _hit_extras(hit: dict[str, Any]) -> dict[str, Any] | None:
    """``extras`` is indexed as a JSON string (``payload_text``)."""
    extras = hit.get("extras")
    if isinstance(extras, dict):
        return extras
    raw = hit.get("payload_text")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except ValueError:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def _path_words(parts: list[str]) -> set[str]:
    """Every distinct word in these path segments, normalised."""
    return {word for part in parts for word in _norm(part).split()}


def pick_mapped_category(
    general: dict[str, Any],
    match: dict[str, Any] | None,
    recommendations: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """The best of Vendoo's mapping answers for a general category.

    Its ``match`` is a single guess and is sometimes the wrong branch — a
    girls' t-shirt came back as Boys' on eBay and as Tanks on Etsy, with the
    right leaf sitting in ``recommendations``. Score them all against the
    general category the seller chose: agreeing with its leaf counts most,
    then agreeing anywhere in the path. The match keeps ties, so this only
    overrides it when something genuinely fits better.
    """
    candidates = [c for c in [match, *(recommendations or [])] if isinstance(c, dict) and c.get("id")]
    if not candidates:
        return None
    want_parts = [str(part) for part in (general.get("displayPath") or [])]
    if not want_parts:
        return candidates[0]
    want_all = _path_words(want_parts)
    want_leaf = _path_words(want_parts[-1:])

    def score(candidate: dict[str, Any]) -> tuple[int, int]:
        parts = [str(part) for part in hit_display_path(candidate)]
        if not parts:
            return (0, 0)
        return (
            len(want_leaf & _path_words(parts[-1:])),
            len(want_all & _path_words(parts)),
        )

    best = max(range(len(candidates)), key=lambda i: (*score(candidates[i]), -i))
    return candidates[best]


def category_from_hit(hit: dict[str, Any] | None, fallback_path: str = "") -> dict[str, Any] | None:
    """Turn a ``/api/category/search`` hit into Vendoo's full ``categoryV2``.

    The picker stores more than ``{id, displayPath}``: the eBay form needs the
    ancestor id chain and ``extras.siteId`` to look the leaf's aspects up, and
    throws without them. Anything the hit does not carry is left off rather
    than invented, so a thin hit still yields the minimal object.
    """
    if not isinstance(hit, dict):
        return category_v2(path=fallback_path)
    cat_id = hit.get("id") or hit.get("category_id") or hit.get("value") or hit.get("key")
    out = category_v2(cat_id, hit_display_path(hit) or fallback_path)
    if not out:
        return None
    label = hit.get("last_subcategory_label") or hit.get("most_relevant_text") or hit.get("displayName")
    if isinstance(label, str) and label.strip():
        out["displayName"] = label.strip()
    for source, dest in (("is_leaf", "isLeaf"), ("isLeaf", "isLeaf"),
                         ("has_children", "hasChildren"), ("hasChildren", "hasChildren")):
        if dest not in out and hit.get(source) is not None:
            out[dest] = bool(hit[source])
    ancestors = hit.get("parent_category_id_path")
    if isinstance(ancestors, list) and cat_id:
        chain = [str(part) for part in ancestors if str(part or "").strip()]
        out["path"] = [*chain, str(cat_id)]
    extras = _hit_extras(hit)
    if extras is not None:
        out["extras"] = extras
    return out


def _resolved_category(listing: dict[str, Any], marketplace: str) -> dict[str, Any] | None:
    """The full ``categoryV2`` the resolver stashed for this marketplace."""
    objects = listing.get("marketplace_category_objects")
    hit = objects.get(marketplace) if isinstance(objects, dict) else None
    return dict(hit) if isinstance(hit, dict) and hit.get("id") else None


def _category(listing: dict[str, Any]) -> Any:
    """Prefer a resolved Vendoo category object; fall back to the display path."""
    resolved = _resolved_category(listing, "general")
    if resolved:
        return resolved
    resolved = category_v2(listing.get("category_id"), listing.get("category_path"))
    if resolved and resolved.get("id"):
        return resolved
    path = _clean(listing.get("category_path"))
    return path


def _size(listing: dict[str, Any], category_id: Any = None) -> dict[str, Any] | None:
    """The general form's size, as Vendoo stores it.

    ``categoryId`` ties the size to the general category; without it the form
    has no scale to read the option against. Options and scales are their own
    labels here — Vendoo's size vocabulary is not coded.
    """
    size = _clean(listing.get("size")) or _clean(listing.get("size_us"))
    scale = _clean(listing.get("sizeType"))
    if not size and not scale:
        return None
    out: dict[str, Any] = {
        "option": {"label": size or "", "value": size or ""},
        "scale": {"label": scale or "", "value": scale or ""},
    }
    category = _clean(category_id)
    if category:
        out["categoryId"] = category
    return out


def _general_details(
    listing: dict[str, Any],
    schema: dict[str, Any] | None,
    images: list[Any],
    unresolved: list[dict[str, str]],
) -> dict[str, Any]:
    general = default_general_details()

    def coded(name: str, label: Any) -> Any:
        text = _clean(label)
        value, ok = encode_field(schema, name, text)
        if not ok and text and name in ("primaryColor", "secondaryColor"):
            # What the seller's own items taught us wins — it carries the shape
            # this account stores. Vendoo's shipped vocabulary only rescues a
            # colour they have not used before, which is otherwise reported.
            known = GENERAL_COLORS.get(_norm(text))
            if known:
                return known
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
        general["category"] = None
    elif category:
        general["category"] = category
    size = _size(listing, (general.get("categoryV2") or {}).get("id") if isinstance(general.get("categoryV2"), dict) else None)
    if size:
        general["size"] = size
    weight_lb, weight_oz = listing.get("weight_lb"), listing.get("weight_oz")
    if weight_lb not in (None, "") or weight_oz not in (None, ""):
        general["weight"] = {"pounds": _num_str(weight_lb or 0), "ounces": _num_str(weight_oz or 0)}
    dims = _dimensions(listing.get("package_dimensions_in"))
    if dims:
        general["dimensions"] = dims
    return general


def _field_words(name: Any) -> str:
    """``sleeveLength`` and ``Sleeve Length`` both reduce to ``sleeve length``."""
    return _norm(_CAMEL_BOUNDARY.sub(" ", str(name or "")))


def _spec_index(specs: dict[str, FieldSpec]) -> dict[str, FieldSpec]:
    """Every field of a category, reachable by its key or its label's words."""
    index: dict[str, FieldSpec] = {}
    for key, spec in specs.items():
        index.setdefault(_field_words(key), spec)
        index.setdefault(_field_words(spec.display), spec)
    return index


def _category_specifics(
    category_id: str,
    specs: dict[str, FieldSpec],
    studio_specifics: dict[str, Any],
    listing: dict[str, Any],
    unresolved: list[dict[str, str]],
    marketplace: str,
) -> dict[str, Any]:
    """Encode Studio's values as the ``{categoryId}_{field}`` map Vendoo stores.

    Vendoo's schema for the chosen category decides everything: which keys
    exist, which hold a list (``maxValues > 1``) and which accept only a coded
    option id. A value that a ``SelectionOnly`` field has no option for is
    reported instead of stored — storing it is what makes the form's own lookup
    return undefined and crash the marketplace tab.
    """
    merged = dict(studio_specifics)
    for key in ("size", "sizeType", "department", "type", "brand"):
        if merged.get(key) in (None, "", []) and listing.get(key) not in (None, "", []):
            merged[key] = listing[key]

    index = _spec_index(specs)
    out: dict[str, Any] = {}
    for studio_key, value in merged.items():
        words = _field_words(studio_key)
        if not words or words in _NOT_CATEGORY_FIELDS:
            continue
        spec = index.get(words)
        if spec is None:
            continue
        if spec.scales:
            # Size and friends: Vendoo stores the chosen scale alongside the
            # value, and the value alone means nothing without it.
            chosen_scale, code, resolved = encode_scaled(spec, value)
            if not resolved:
                unresolved.append({"field": f"{marketplace}:{spec.display}", "value": str(value)})
                continue
            if code:
                out[specifics_key(category_id, spec.key)] = code
                out[scale_key(category_id, spec.key)] = chosen_scale
            continue
        stored, resolved = encode_specific(spec, value)
        if not resolved:
            unresolved.append({
                "field": f"{marketplace}:{spec.display}",
                "value": ", ".join(str(part) for part in (value if isinstance(value, list) else [value])),
            })
            continue
        if stored in (None, "", []):
            continue
        out[specifics_key(category_id, spec.key)] = stored
    return out


def _learned_category_specifics(
    category_id: str,
    studio_specifics: dict[str, Any],
    listing: dict[str, Any],
    schema: dict[str, Any] | None = None,
    marketplace: str = "ebay",
) -> dict[str, Any]:
    """Fallback for when Vendoo's schema for the leaf could not be fetched.

    Field names and their list-vs-scalar shapes come from the seller's own
    items via ``observe_listing_encodings``, so only fields their account has
    already used get written. Anything else is left out rather than guessed.
    """
    merged = dict(studio_specifics)
    for key in ("size", "sizeType", "department", "type", "brand"):
        if merged.get(key) in (None, "", []) and listing.get(key) not in (None, "", []):
            merged[key] = listing[key]
    shapes = ((schema or {}).get("aspects") or {}).get(marketplace) or {}
    index = {_field_words(suffix): suffix for suffix in shapes}
    out: dict[str, Any] = {}
    for studio_key, value in merged.items():
        words = _field_words(studio_key)
        if not words or words in _NOT_CATEGORY_FIELDS:
            continue
        suffix = index.get(words)
        if not suffix:
            continue
        if isinstance(value, list):
            parts = [str(part).strip() for part in value if str(part or "").strip()]
        else:
            parts = [str(value).strip()] if str(value or "").strip() else []
        if not parts:
            continue
        out[specifics_key(category_id, suffix)] = (
            parts if aspect_is_multi(schema, marketplace, suffix) else ", ".join(parts)
        )
    return out


def _listing_section(
    marketplace: str,
    listing: dict[str, Any],
    general: dict[str, Any],
    schema: dict[str, Any] | None = None,
    unresolved: list[dict[str, str]] | None = None,
    specs: dict[str, FieldSpec] | None = None,
) -> dict[str, Any]:
    """Fill one marketplace section from ``<marketplace>_specifics``.

    Known ``marketplaceSpecifics`` keys land there and a resolved leaf becomes
    ``overrides.categoryV2``. Once that leaf is known, its item fields are
    written as ``{categoryId}_{field}``. ``specs`` is Vendoo's own schema for
    that leaf and is authoritative when present — it is the only thing that
    knows which fields hold lists and which coded option ids are legal. Without
    it we fall back to what ``observe_listing_encodings`` learned from the
    seller's existing items.
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
    parts = path_parts(path)
    if not parts:
        cats = listing.get("marketplace_categories")
        if isinstance(cats, dict):
            parts = path_parts(cats.get(marketplace))
    cat_ids = listing.get("marketplace_category_ids")
    cat_id = None
    if isinstance(cat_ids, dict):
        cat_id = cat_ids.get(marketplace)
    cat_id = specifics.pop("categoryId", None) or specifics.pop("category_id", None) or cat_id
    # Snapshot before the marketplaceSpecifics pass prunes Studio-only keys.
    # Marketplace form fields that live in marketplaceSpecifics (style, age,
    # shipping, …) must not be fed to the category-aspects encoder — a leaf
    # field with the same label would consume them. Size/brand stay in aspects.
    aspects = {
        key: value for key, value in specifics.items()
        if key not in known and key != "category_specifics"
    }
    for key in list(specifics.keys()):
        if key in _STUDIO_ONLY_SPECIFIC_KEYS or key == "category_specifics":
            specifics.pop(key, None)

    resolved = _resolved_category(listing, marketplace) or category_v2(cat_id, parts)
    if resolved:
        section["overrides"]["categoryV2"] = resolved

    if resolved and resolved.get("id"):
        leaf_id = str(resolved["id"])
        reports = unresolved if unresolved is not None else []
        # The seller's own wording encodes against the leaf's options; the
        # coded generalDetails value is only a fallback for it.
        candidate_conditions = [
            value for value in (listing.get("condition"), general.get("condition"))
            if value not in (None, "")
        ]
        raw_condition = candidate_conditions[0] if candidate_conditions else None
        if specs:
            section["categorySpecifics"] = _category_specifics(
                leaf_id, specs, aspects, listing, reports, marketplace
            )
            condition_spec = specs.get("condition") or specs.get("Condition")
            if condition_spec is not None and candidate_conditions:
                for candidate in candidate_conditions:
                    code, ok = encode_specific(condition_spec, candidate)
                    if ok and code not in (None, "", []):
                        # The leaf keeps its condition in both places, as its id.
                        section["overrides"]["condition"] = code
                        section["categorySpecifics"][specifics_key(leaf_id, condition_spec.key)] = code
                        break
                else:
                    reports.append({
                        "field": f"condition:{marketplace}",
                        "value": str(candidate_conditions[0]),
                    })
            for field in missing_required(specs, section["categorySpecifics"], leaf_id):
                reports.append({"field": f"{marketplace}:{field}", "value": ""})
        elif marketplace == "ebay":
            section["categorySpecifics"] = _learned_category_specifics(
                leaf_id, aspects, listing, schema
            )
            code = marketplace_condition(schema, marketplace, raw_condition)
            if code not in (None, ""):
                section["overrides"]["condition"] = code
                section["categorySpecifics"][f"{leaf_id}_condition"] = code
            elif raw_condition not in (None, ""):
                reports.append({"field": f"condition:{marketplace}", "value": str(raw_condition)})

    for key, value in specifics.items():
        if value in (None, "", []):
            continue
        dest = ETSY_KEY_MAP.get(key, key) if marketplace == "etsy" else key
        if dest not in known:
            continue
        if isinstance(known[dest], dict) and isinstance(value, dict):
            known[dest] = {**known[dest], **value}
        elif isinstance(known[dest], list):
            known[dest] = _string_list(value)
        elif dest == "originalPrice":
            known[dest] = _num_str(value)
        else:
            known[dest] = value

    # Mercari shipping label is Studio wording for the prepaid carrier id.
    if marketplace == "mercari":
        label = ""
        raw_mercari = listing.get("mercari_specifics")
        if isinstance(raw_mercari, dict):
            label = _clean(raw_mercari.get("shippingLabel") or raw_mercari.get("shipping_label")) or ""
        if not label or "ground advantage" in _norm(label):
            shipping = known.setdefault("shipping", {})
            if isinstance(shipping, dict):
                shipping.setdefault("deliveryMethod", "mercari_shipping")
                shipping.setdefault("payerId", 1)
                shipping["carrierId"] = MERCARI_GROUND_ADVANTAGE_CARRIER

    _apply_marketplace_brand(section, marketplace, listing)
    return section


def _firestore_now() -> dict[str, int]:
    """A Firestore timestamp, the shape saved items carry."""
    import time

    now = time.time()
    return {"_seconds": int(now), "_nanoseconds": int((now % 1) * 1_000_000_000)}


def _mark_saved(item: dict[str, Any], *, incomplete: bool = False) -> None:
    """Record the item as saved, the way Vendoo's own save does.

    A new item starts ``{"notSaved": True}`` — literally "Not Saved" in
    Vendoo's UI — and its save replaces that with ``complete`` or
    ``inProgress`` depending on whether anything required is still missing,
    stamping every marketplace form it wrote. Creating an item without doing
    the same leaves every form looking untouched.
    """
    # Complete, not inProgress: a draft Studio created is finished work as far
    # as Studio is concerned. Vendoo recomputes this on its own next save, so
    # a required field still missing will show there rather than here.
    item["status"] = {"complete": True}
    stamp = _firestore_now()
    for section in (item.get(LISTINGS_KEY) or {}).values():
        if not isinstance(section, dict):
            continue
        # Only forms that were actually filled out.
        if not (section.get("categorySpecifics") or (section.get("overrides") or {}).get("categoryV2")):
            continue
        section["dateCreated"] = stamp
        section["dateLastModified"] = stamp


def build_vendoo_item(
    listing: dict[str, Any],
    schema: dict[str, Any] | None = None,
    *,
    images: list[Any] | None = None,
    user_id: str = "",
    item_id: str = "",
    origin: str = DEFAULT_ORIGIN,
    specifics: dict[str, dict[str, FieldSpec]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """A complete Vendoo item, shaped exactly like a form save.

    ``images`` are the ``{version: 3, id, originalMaxDimension}`` objects the
    inventory upload returns. ``specifics`` maps a marketplace to Vendoo's own
    field schema for the leaf chosen there; where it is present the item fields
    are encoded exactly as that marketplace's form would store them.

    Returns ``(item, unresolved)``; ``unresolved`` names every field sent as
    plain text because nothing covered it, every value a coded field had no
    option for, and every required field left empty — show those to the seller
    rather than assuming they landed.
    """
    unresolved: list[dict[str, str]] = []
    by_marketplace = specifics or {}
    general = _general_details(listing, schema, images or [], unresolved)
    listings = {
        mp: _listing_section(mp, listing, general, schema, unresolved, by_marketplace.get(mp))
        for mp in ALL_MARKETPLACES
    }
    item = {
        "origin": origin,
        "version": CURRENT_ITEM_VERSION,
        "status": {"notSaved": True},  # replaced by _mark_saved below
        "type": "item",
        "userID": user_id,
        "itemID": item_id,
        "labels": _string_list(listing.get("labels")),
        GENERAL_KEY: general,
        LISTINGS_KEY: listings,
    }
    _mark_saved(item)
    return item, unresolved


# Only the parts of an item Studio is responsible for. Vendoo owns the rest —
# ids, dates, listing state — and a save must not reach into them.
_OWNED_LISTING_BUCKETS = ("overrides", "categorySpecifics", "marketplaceSpecifics")


def changed_fields(current: dict[str, Any], desired: dict[str, Any]) -> dict[str, str | Any]:
    """Dotted Firestore paths where ``desired`` differs from what Vendoo holds.

    Vendoo's own edit writes just the touched paths rather than the whole
    document, so an unrelated field a seller changed in Vendoo survives a save
    from Studio. Empty values in ``desired`` are skipped: Studio not knowing
    something is not the same as the seller clearing it.
    """
    out: dict[str, Any] = {}

    def walk(prefix: str, want: Any, have: Any) -> None:
        if isinstance(want, dict):
            for key, value in want.items():
                walk(f"{prefix}.{key}" if prefix else key, value, (have or {}).get(key) if isinstance(have, dict) else None)
            return
        if want in (None, "", []):
            return
        # Brand labels are case-sensitive on the form (``Unbranded`` ≠ ``unbranded``).
        if prefix.endswith(".brand") or prefix.endswith(".noBrand"):
            if want != have:
                out[prefix] = want
            return
        if _comparable(want) != _comparable(have):
            out[prefix] = want

    general_want = desired.get(GENERAL_KEY) or {}
    general_have = current.get(GENERAL_KEY) or {}
    for key, value in general_want.items():
        if key == "images":  # uploaded separately; never re-sent as a diff
            continue
        walk(f"{GENERAL_KEY}.{key}", value, general_have.get(key))

    listings_want = desired.get(LISTINGS_KEY) or {}
    listings_have = current.get(LISTINGS_KEY) or {}
    for marketplace, section in listings_want.items():
        if not isinstance(section, dict):
            continue
        have_section = listings_have.get(marketplace) or {}
        for bucket in _OWNED_LISTING_BUCKETS:
            if not isinstance(section.get(bucket), dict):
                continue
            for key, value in section[bucket].items():
                if key == "images":
                    continue
                walk(
                    f"{LISTINGS_KEY}.{marketplace}.{bucket}.{key}",
                    value,
                    (have_section.get(bucket) or {}).get(key),
                )
    return out


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
