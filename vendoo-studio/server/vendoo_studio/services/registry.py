from __future__ import annotations

import re

from sqlalchemy.orm import Session

from vendoo_studio.models.mercari_shipping import DEFAULT_SHIPPING_LABEL
from vendoo_studio.repositories.queries import RegistryRepo, _normalize_label


CANONICAL_DEFAULTS: dict[str, dict[str, str]] = {
    "mercari": {
        "shipping label": DEFAULT_SHIPPING_LABEL,
        # Mercari has no "Other" brand — an unlisted brand is the No Brand checkbox.
        "brand": "No Brand/Not sure",
    },
    "poshmark": {
        "original price": "0",
    },
    "depop": {
        "brand": "Other",
    },
}

LEARNED_MARKETPLACES = ("ebay", "etsy", "poshmark", "mercari", "depop")

# Caps how many live dropdown options are spelled out per field in the prompt.
MAX_PROMPT_OPTIONS = 80

# Form labels that are seller/account UI, not item attributes.
SELLER_SETTING_LABELS = frozenset({
    "allow best offer",
    "auto-accept",
    "auto accept",
    "minimum offer",
    "minimum price",
    "primary store category",
    "secondary store category",
    "personalization instructions",
    "exclude sku from listing",
    "no brand/not sure",
    "worldwide shipping",
    "custom property",
    "other info",
    "size grouping",
    "accept returns",
    "return within",
    "return refund method",
    "return paid by",
    "return payed by",
    "returns",
    "starting price",
    "payment method",
})

# Only Depop (parcel size) and Mercari (shipping label) price shipping per item.
# Every other form reads shipping from the seller's saved marketplace settings.
ITEM_SHIPPING_MARKETPLACES = frozenset({"depop", "mercari"})

# Return/payment/handling terms are fixed in marketplace settings on every form.
_POLICY_LABEL_RE = re.compile(
    r"\b(polic(?:y|ies)|returns?|refunds?|handling time|processing (?:time|profile)|"
    r"payment method|ready to ship)\b"
)
# Package weight and dimensions are item data wherever they appear — never matched here.
_SHIPPING_LABEL_RE = re.compile(
    r"\b(shipping|shipment|ship to|shipped|delivery|parcel|postage|carrier|"
    r"package (?:type|size)|who pays)\b"
)

# Already stored on the listing root (or a general field). Do not copy into *_specifics.
ROOT_FIELD_LABELS = frozenset({
    "title",
    "description",
    "price",
    "listing price",
    "quantity",
    "sku",
    "brand",
    "condition",
    "size",
    "size type",
    "primary color",
    "secondary color",
    "color",
    "tags",
    "notes",
    "category",
    "cost of goods",
    "weight (lbs)",
    "weight (oz)",
    "length",
    "width",
    "height",
    "labels",
    "zip code",
    "zipcode",
})

LABEL_TO_JSON_KEY = {
    "size type": "sizeType",
    "sleeve length": "sleeveLength",
    "sleeve type": "sleeveType",
    "country of origin": "countryOfOrigin",
    "fabric type": "fabricType",
    "fabric weight": "fabricWeight",
    "garment care": "garmentCare",
    "unit quantity": "unitQuantity",
    "unit type": "unitType",
    "character family": "characterFamily",
    "performance activity": "performanceActivity",
    "year manufactured": "yearManufactured",
    "collar style": "collarStyle",
    "strap type": "strapType",
    "clothing style": "clothingStyle",
    "fabric pattern": "fabricPattern",
    "who made": "who_made",
    "what is it": "what_is",
    "when made": "when_made",
    "original price": "originalPrice",
    "shipping label": "shippingLabel",
    "style tags": "styleTags",
}


WOMEN_TOPS_PATH = "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops"
MEN_TSHIRT_PATH = "Clothing, Shoes & Accessories > Men > Men's Clothing > Shirts > T-Shirts"
MEN_SHIRTS_PATH = "Clothing, Shoes & Accessories > Men > Men's Clothing > Shirts"
POSHMARK_MEN_SHORT_TEE = "Men > Shirts > Tees - Short Sleeve"
POSHMARK_MEN_LONG_TEE = "Men > Shirts > Tees - Long Sleeve"
POSHMARK_WOMEN_SHORT_TEE = "Women > Tops > Tees - Short Sleeve"
POSHMARK_WOMEN_LONG_TEE = "Women > Tops > Tees - Long Sleeve"
POSHMARK_WOMEN_BLOUSE = "Women > Tops > Blouses"
MERCARI_WOMEN_BLOUSE = "Women > Tops & blouses > Blouse"
MERCARI_WOMEN_TEE = "Women > Tops & blouses > T-shirts"
DEPOP_WOMEN_TEE = "Women > Tops > T-shirts"
DEPOP_WOMEN_BLOUSE = "Women > Tops > Blouses"
DEPOP_WOMEN_SHIRT = "Women > Tops > Shirts"
ETSY_WOMEN_TEE = "Clothing > Women's Clothing > Tops & Tees > T-shirts"
ETSY_WOMEN_BLOUSE = "Clothing > Women's Clothing > Tops & Tees > Blouses"

# Each marketplace's women's top leaves, by the kind of top the listing names.
# A kind with no leaf here falls back through TOP_KIND_FALLBACKS, and failing
# that the listing keeps whatever Vendoo mapped rather than being guessed at.
WOMEN_TOP_LEAVES: dict[str, dict[str, str]] = {
    "poshmark": {
        "tee": POSHMARK_WOMEN_SHORT_TEE,
        "long_tee": POSHMARK_WOMEN_LONG_TEE,
        "blouse": POSHMARK_WOMEN_BLOUSE,
        "button_up": "Women > Tops > Button Down Shirts",
        "tank": "Women > Tops > Tank Tops",
        "cami": "Women > Tops > Camisoles",
        "crop": "Women > Tops > Crop Tops",
        "muscle": "Women > Tops > Muscle Tees",
        "bodysuit": "Women > Tops > Bodysuits",
        "jersey": "Women > Tops > Jerseys",
        "tunic": "Women > Tops > Tunics",
    },
    "mercari": {
        "tee": MERCARI_WOMEN_TEE,
        "blouse": MERCARI_WOMEN_BLOUSE,
        "button_up": "Women > Tops & blouses > Button down shirt",
        "tank": "Women > Tops & blouses > Tank Tops",
        "cami": "Women > Tops & blouses > Camisoles",
        "halter": "Women > Tops & blouses > Halter",
        "polo": "Women > Tops & blouses > Polo shirt",
        "turtleneck": "Women > Tops & blouses > Turtleneck",
        "bodysuit": "Women > Tops & blouses > Bodysuits",
        "tunic": "Women > Tops & blouses > Tunic",
    },
    "depop": {
        "tee": DEPOP_WOMEN_TEE,
        "blouse": DEPOP_WOMEN_BLOUSE,
        "button_up": DEPOP_WOMEN_SHIRT,
        "tank": "Women > Tops > Tank tops and camis",
        "cami": "Women > Tops > Tank tops and camis",
        "crop": "Women > Tops > Crop tops",
        "polo": "Women > Tops > Polo shirts",
        "bodysuit": "Women > Tops > Bodysuits",
        "jersey": "Women > Tops > Jerseys",
        "corset": "Women > Tops > Corsets",
    },
    "etsy": {
        "tee": ETSY_WOMEN_TEE,
        "blouse": ETSY_WOMEN_BLOUSE,
        "tank": "Clothing > Women's Clothing > Tops & Tees > Tanks",
        "crop": "Clothing > Women's Clothing > Tops & Tees > Crop & Tube Tops > Crop Tops",
        "tube": "Clothing > Women's Clothing > Tops & Tees > Crop & Tube Tops > Tube Tops",
        "halter": "Clothing > Women's Clothing > Tops & Tees > Halter Tops",
        "polo": "Clothing > Women's Clothing > Tops & Tees > Polos",
        "tunic": "Clothing > Women's Clothing > Tops & Tees > Tunics",
    },
}
# Where to look when a marketplace has no leaf for the kind the listing names.
TOP_KIND_FALLBACKS: dict[str, tuple[str, ...]] = {
    "long_tee": ("tee",),
    "button_up": ("blouse",),
    "tank": ("cami",),
    "cami": ("tank",),
    "crop": ("tee",),
    "tube": ("tank",),
    "halter": ("tank",),
    "muscle": ("tee",),
    "jersey": ("tee",),
    "tunic": ("blouse",),
    "corset": (),
    "polo": (),
    "turtleneck": (),
    "bodysuit": (),
}

# Canonical leaves to seed when the seller/photo intent is a broad women's top.
WOMEN_TOPS_SEEDS: dict[str, list[str]] = {
    "general": [WOMEN_TOPS_PATH],
    "ebay": [WOMEN_TOPS_PATH],
    "poshmark": [POSHMARK_WOMEN_SHORT_TEE, POSHMARK_WOMEN_BLOUSE, POSHMARK_WOMEN_LONG_TEE],
    "mercari": [MERCARI_WOMEN_TEE, MERCARI_WOMEN_BLOUSE],
    "depop": [DEPOP_WOMEN_TEE, DEPOP_WOMEN_BLOUSE, DEPOP_WOMEN_SHIRT],
    "etsy": [ETSY_WOMEN_TEE, ETSY_WOMEN_BLOUSE],
}

CATEGORY_NORMALIZATIONS: dict[str, dict[str, str]] = {
    "general": {
        "women's shirts & blouses": WOMEN_TOPS_PATH,
        "women's t-shirts": WOMEN_TOPS_PATH,
        "women's tops": WOMEN_TOPS_PATH,
        "women > clothing > tops": WOMEN_TOPS_PATH,
        "women > clothing > tops > t-shirts": WOMEN_TOPS_PATH,
        "women > women's clothing > tops": WOMEN_TOPS_PATH,
        "clothing > women's clothing > tops": WOMEN_TOPS_PATH,
        "clothing > women's clothing > t-shirts": WOMEN_TOPS_PATH,
        "clothing > women's clothing > shirts & blouses": WOMEN_TOPS_PATH,
        "men's t-shirts": MEN_TSHIRT_PATH,
        "men's shirts": MEN_SHIRTS_PATH,
        "men > clothing > tops > t-shirts": MEN_TSHIRT_PATH,
        "clothing > men's clothing > shirts > t-shirts": MEN_TSHIRT_PATH,
    },
}

_TOP_ITEM_RE = re.compile(r"\bt-?shirts?\b|\btees?\b|\btops?\b|\bshirts?\b|\bblouses?\b", re.I)
_TEE_ITEM_RE = re.compile(r"\bt-?shirts?\b|\btees?\b", re.I)
_NON_TOP_RE = re.compile(
    # "dresses?" would read as "dresse" plus an optional s and miss the singular.
    r"\bdress(?:es)?\b|\bpants?\b|\bjeans?\b|\bskirts?\b|\bshorts?\b|\bjackets?\b|"
    r"\bcoats?\b|\bsweatshirts?\b|\bsweaters?\b|\bhoodies?\b|\bshoes?\b|\bbags?\b",
    re.I,
)
_WOMEN_RE = re.compile(r"\bwomen(?:['’]s)?\b", re.I)
_MEN_RE = re.compile(r"\bmen(?:['’]s)?\b", re.I)
_GENDER_PATH_RE = re.compile(r"(?:department|category_path|categorypath)$", re.I)


def _category_key(category: str) -> str:
    return " > ".join(part.strip().lower() for part in category.split(">") if part.strip())


def _path_leaf(category: str) -> str:
    parts = [part.strip() for part in category.split(">") if part.strip()]
    return parts[-1] if parts else ""


def _listing_text(listing: dict | None) -> str:
    listing = listing or {}
    specifics = listing.get("ebay_specifics") if isinstance(listing.get("ebay_specifics"), dict) else {}
    return " ".join(
        str(part)
        for part in (
            listing.get("department"),
            specifics.get("department") if isinstance(specifics, dict) else "",
            specifics.get("type") if isinstance(specifics, dict) else "",
            listing.get("type"),
            listing.get("title"),
        )
        if part
    )


def _gender_from_text(text: str) -> str | None:
    has_women = bool(_WOMEN_RE.search(text or ""))
    has_men = bool(_MEN_RE.search(text or ""))
    if has_men and not has_women:
        return "men"
    if has_women and not has_men:
        return "women"
    return None


def _listing_gender(listing: dict | None, extra: str = "") -> str | None:
    """Prefer explicit department over leftover Women/Men words in an old category path."""
    listing = listing or {}
    specifics = listing.get("ebay_specifics") if isinstance(listing.get("ebay_specifics"), dict) else {}
    for value in (
        listing.get("department"),
        specifics.get("department") if isinstance(specifics, dict) else None,
    ):
        gender = _gender_from_text(str(value or ""))
        if gender:
            return gender
    return _gender_from_text(f"{extra} {listing.get('title') or ''}")


def _gender_from_patch(operations: list[dict] | None) -> str | None:
    if not operations:
        return None
    found = None
    for op in operations:
        if not isinstance(op, dict) or op.get("op") not in {"replace", "add"}:
            continue
        path = str(op.get("path") or "").rstrip("/")
        if not _GENDER_PATH_RE.search(path):
            continue
        gender = _gender_from_text(str(op.get("value") or ""))
        if gender:
            found = gender
    return found


def _apply_department(listing: dict, gender: str) -> None:
    label = "Men" if gender == "men" else "Women"
    listing["department"] = label
    ebay = listing.get("ebay_specifics")
    if isinstance(ebay, dict) and str(ebay.get("department") or "").strip():
        ebay["department"] = label


def align_listing_gender(listing: dict, operations: list[dict] | None = None) -> dict:
    """Keep department and Vendoo category on the same gender after a chat revision."""
    if not isinstance(listing, dict):
        return listing
    gender = _gender_from_patch(operations) or _listing_gender(
        listing, str(listing.get("category_path") or ""),
    )
    if gender in {"men", "women"}:
        _apply_department(listing, gender)
    mapped = map_vendoo_category_path(str(listing.get("category_path") or ""), listing)
    if mapped:
        listing["category_path"] = mapped
    return listing


def map_vendoo_category_path(category: str, listing: dict | None = None) -> str:
    """Map marketplace or abbreviated paths onto a selectable Vendoo General leaf."""
    raw = (category or "").strip()
    if not raw and isinstance(listing, dict):
        raw = str(listing.get("category_path") or "").strip()
    if not raw:
        return raw

    if _NON_TOP_RE.search(_path_leaf(raw)):
        return raw

    norms = CATEGORY_NORMALIZATIONS.get("general", {})
    alias = norms.get(raw.lower()) or norms.get(_category_key(raw))
    haystack = f"{raw} {_listing_text(listing)}"
    gender = _listing_gender(listing, raw)
    is_top = bool(_TOP_ITEM_RE.search(haystack))
    if gender == "women" and is_top:
        return WOMEN_TOPS_PATH
    if gender == "men" and _TEE_ITEM_RE.search(haystack):
        return MEN_TSHIRT_PATH
    if alias:
        return alias
    return raw


_TEE_RE = re.compile(r"\bt-?shirts?\b|\btees?\b|graphic tee", re.I)
_LONG_SLEEVE_RE = re.compile(r"long\s*sleeve", re.I)
_SHORT_SLEEVE_RE = re.compile(r"short\s*sleeve", re.I)
_BLOUSE_RE = re.compile(r"\bblouses?\b", re.I)
_BUTTON_UP_RE = re.compile(r"button[\s-]*(up|front|down)", re.I)
_POSHMARK_ROOT_RE = re.compile(r"^(men|women|kids|pets|home|electronics)\s*>", re.I)
_TANK_PATH_RE = re.compile(r"\btank\b", re.I)
_TUNIC_PATH_RE = re.compile(r"\btunics?\b", re.I)
_TUNIC_STYLE_RE = re.compile(r"\btunic\b", re.I)
_SLEEVELESS_ITEM_RE = re.compile(r"\b(?:sleeveless|tank|cami|halter|strapless)\b", re.I)
_ETSY_ROOT_RE = re.compile(r"^clothing\s*>", re.I)
_MERCARI_ROOT_RE = re.compile(r"^(women|men|kids|unisex)\s*>", re.I)
_DEPOP_ROOT_RE = re.compile(r"^(women|men|kids)\s*>", re.I)
# Every garment word these mappers can read, top or not. The last one a title
# names is the garment itself. Shorts stays plural: "Short Sleeve" is a sleeve.
_GARMENT_HEAD_RE = re.compile(
    r"\b(?:t-?shirts?|tees?|tops?|blouses?|shirts?|tunics?|tanks?|dress(?:es)?|"
    r"pants?|jeans?|skirts?|shorts|leggings?|jumpsuits?|rompers?|jackets?|coats?|"
    r"sweatshirts?|sweaters?|hoodies?|shoes?|bags?)\b",
    re.I,
)
# Leaf words naming a top that is not a plain tee. Such a leaf is only right
# when the listing itself says the same word.
_SPECIFIC_TOP_LEAF_RE = re.compile(
    r"tunics?|tanks?|camis(?:oles?)?|halters?|crop|tube|polos?|turtlenecks?|bodysuits?|"
    r"wrap|knit|button|corsets?|jerseys?|cardigans?|sweaters?|sweatshirts?|hoodies?|"
    r"blouses?|shirts?",
    re.I,
)


# The kind of top a listing names, most specific cue first. "Blouse" beats a
# button-up cue: a listing that says blouse is one, whatever its placket.
_TOP_KIND_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("bodysuit", re.compile(r"\bbodysuits?\b", re.I)),
    ("corset", re.compile(r"\bcorsets?\b|\bbustiers?\b", re.I)),
    ("tunic", _TUNIC_STYLE_RE),
    ("halter", re.compile(r"\bhalters?\b", re.I)),
    ("tube", re.compile(r"\btube\s*tops?\b", re.I)),
    ("crop", re.compile(r"\bcrops?(?:\s*tops?)?\b|\bcropped\b", re.I)),
    ("cami", re.compile(r"\bcamis(?:oles?)?\b", re.I)),
    ("tank", re.compile(r"\btanks?\b|\bsleeveless\b", re.I)),
    ("muscle", re.compile(r"\bmuscle\s*(?:tees?|shirts?|tanks?)\b", re.I)),
    ("polo", re.compile(r"\bpolos?\b", re.I)),
    ("turtleneck", re.compile(r"\bturtlenecks?\b|\bmock\s*necks?\b", re.I)),
    ("jersey", re.compile(r"\bjerseys?\b", re.I)),
    ("blouse", _BLOUSE_RE),
    ("button_up", _BUTTON_UP_RE),
    ("tee", _TEE_RE),
)
# Sleeves rule these out: "Short Sleeve Tank" is the mapper reading a leaf it
# was handed, not the seller describing a tank.
_SLEEVED_KINDS = frozenset({"tank", "cami", "halter", "tube"})


def _top_kind(haystack: str) -> str | None:
    """Which kind of top the listing names, if it names one at all."""
    sleeved = bool(_SHORT_SLEEVE_RE.search(haystack) or _LONG_SLEEVE_RE.search(haystack))
    for kind, pattern in _TOP_KIND_RULES:
        if not pattern.search(haystack):
            continue
        if kind in _SLEEVED_KINDS and sleeved:
            continue
        return kind
    return None


def _women_top_leaf(marketplace: str, kind: str, haystack: str) -> str:
    """This marketplace's leaf for that kind of top, or "" when it has none."""
    leaves = WOMEN_TOP_LEAVES.get(marketplace) or {}
    if kind == "tee" and _LONG_SLEEVE_RE.search(haystack) and leaves.get("long_tee"):
        return leaves["long_tee"]
    seen: set[str] = set()
    queue = [kind]
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        if leaves.get(current):
            return leaves[current]
        queue.extend(TOP_KIND_FALLBACKS.get(current, ()))
    return ""


def _kind_of_leaf(leaf: str) -> str | None:
    """The kind a leaf label names, so a leaf can be checked against a listing."""
    for kind, pattern in _TOP_KIND_RULES:
        if pattern.search(leaf):
            return kind
    return None


def _is_blouse_listing(haystack: str) -> bool:
    is_tee = bool(_TEE_RE.search(haystack))
    return (bool(_BLOUSE_RE.search(haystack)) or bool(_BUTTON_UP_RE.search(haystack))) and not is_tee


def _poshmark_haystack(listing: dict, raw: str) -> str:
    ebay = listing.get("ebay_specifics") if isinstance(listing.get("ebay_specifics"), dict) else {}
    sleeve = str(ebay.get("sleeveLength") or "") if isinstance(ebay, dict) else ""
    return f"{raw} {_listing_text(listing)} {sleeve} {listing.get('sleeveLength') or ''} {listing.get('description') or ''}"


def _listing_garment_haystack(listing: dict) -> str:
    """Garment signals from the listing only — never the category path being remapped."""
    ebay = listing.get("ebay_specifics") if isinstance(listing.get("ebay_specifics"), dict) else {}
    sleeve = str(ebay.get("sleeveLength") or "") if isinstance(ebay, dict) else ""
    return (
        f"{_listing_text(listing)} {sleeve} {listing.get('sleeveLength') or ''} "
        f"{listing.get('description') or ''}"
    )


def _stale_tank_path(path: str, listing: dict) -> bool:
    """True when a Tank Tops leaf was mapped for a sleeved tee."""
    if not _TANK_PATH_RE.search(path or ""):
        return False
    garment = _listing_garment_haystack(listing)
    if not _TEE_RE.search(garment):
        return False
    # Real tanks keep the leaf; short/long sleeve wording (or type T-Shirt without
    # sleeveless cues) means the mapper confused parent "Tops" with Tank Tops.
    if _SHORT_SLEEVE_RE.search(garment) or _LONG_SLEEVE_RE.search(garment):
        return True
    return not _SLEEVELESS_ITEM_RE.search(garment)


def _listing_style(listing: dict) -> str:
    ebay = listing.get("ebay_specifics") if isinstance(listing.get("ebay_specifics"), dict) else {}
    return str((ebay or {}).get("style") or listing.get("style") or "")


def _stale_etsy_tunic_path(path: str, listing: dict) -> bool:
    """True when Vendoo mapped bare Women's Tops onto Etsy Tunics for a blouse."""
    if not _TUNIC_PATH_RE.search(path or ""):
        return False
    if _TUNIC_STYLE_RE.search(_listing_style(listing)):
        return False
    garment = f"{_listing_garment_haystack(listing)} {_listing_style(listing)}"
    if _is_blouse_listing(garment):
        return True
    # Button-up / blouse type without a Tunic style is not an Etsy Tunics leaf.
    return bool(_BUTTON_UP_RE.search(garment) or _BLOUSE_RE.search(garment))


def _non_top_listing(listing: dict) -> bool:
    """True when the garment the listing names is not a top.

    English puts the head noun last: a "t-shirt dress" is a dress, a "dress
    shirt" is a shirt. These mappers only know tops, so anything else is left
    to Vendoo's own mapping rather than filed under a T-shirts leaf.
    """
    named = _GARMENT_HEAD_RE.findall(_listing_text(listing))
    return bool(named) and bool(_NON_TOP_RE.search(named[-1]))


def _stale_top_leaf(path: str, listing: dict) -> bool:
    """True when a top was mapped onto a leaf for some other kind of top.

    Vendoo maps the single General "Women's Clothing > Tops" leaf onto one leaf
    per marketplace, so every women's top arrives as whatever that leaf happens
    to be — Tunics on Etsy, Blouse on Mercari, Other on Depop. When the listing
    names a kind of top the marketplace has a leaf for, that leaf wins.
    """
    leaf = _path_leaf(path)
    if not leaf or _non_top_listing(listing):
        return False
    garment = f"{_listing_garment_haystack(listing)} {_listing_style(listing)}"
    kind = _top_kind(garment)
    if kind is None or _kind_of_leaf(leaf) == kind:
        return False
    # A leaf naming a kind the listing does say ("Tank Tops" for a tank tee) is
    # a real choice and stays; one naming nothing it says ("Tops", "Other",
    # "Tunics") is Vendoo's default for every top, not a choice.
    words = {word.casefold().rstrip("s") for word in _SPECIFIC_TOP_LEAF_RE.findall(leaf)}
    if not words:
        return True
    return any(not re.search(rf"\b{re.escape(word)}s?\b", garment, re.I) for word in words)


def _stale_etsy_path(path: str, listing: dict) -> bool:
    return _stale_etsy_tunic_path(path, listing) or _stale_top_leaf(path, listing)


def map_poshmark_category_path(category: str, listing: dict | None = None) -> str:
    """Map a Vendoo/listing category onto a selectable Poshmark path."""
    listing = listing if isinstance(listing, dict) else {}
    raw = (category or "").strip() or str(listing.get("category_path") or "").strip()
    haystack = _poshmark_haystack(listing, raw)
    specifics = listing.get("poshmark_specifics")
    if isinstance(specifics, dict):
        explicit = specifics.get("category_path") or specifics.get("categoryPath")
        explicit_path = ""
        if isinstance(explicit, list):
            explicit_path = " > ".join(str(part).strip() for part in explicit if str(part).strip())
        elif isinstance(explicit, str):
            explicit_path = explicit.strip()
        if explicit_path:
            gender = _listing_gender(listing, raw)
            listing_is_men = gender == "men"
            listing_is_women = gender == "women"
            stale_women = listing_is_men and bool(_WOMEN_RE.search(explicit_path))
            stale_men = listing_is_women and bool(_MEN_RE.search(explicit_path)) and not _WOMEN_RE.search(explicit_path)
            if not stale_women and not stale_men and not _stale_tank_path(explicit_path, listing):
                return explicit_path

    if _POSHMARK_ROOT_RE.search(raw) and not _stale_tank_path(raw, listing):
        return raw
    if _NON_TOP_RE.search(_path_leaf(raw)) or _non_top_listing(listing):
        return raw

    gender = _listing_gender(listing, raw)
    is_women = gender == "women"
    is_men = gender == "men"
    if gender is None:
        is_women = bool(_WOMEN_RE.search(haystack))
        is_men = bool(_MEN_RE.search(haystack)) and not is_women
    # Kinds come from the listing alone: the path being remapped says "Tunics"
    # or "Tank Tops" for every top Vendoo mapped, and would answer for it.
    garment = f"{_listing_garment_haystack(listing)} {_listing_style(listing)}"
    kind = _top_kind(garment)
    if is_men and kind == "tee":
        return POSHMARK_MEN_LONG_TEE if _LONG_SLEEVE_RE.search(garment) else POSHMARK_MEN_SHORT_TEE
    if is_women and kind:
        leaf = _women_top_leaf("poshmark", kind, garment)
        if leaf:
            return leaf
    if is_women and _TOP_ITEM_RE.search(haystack):
        return POSHMARK_WOMEN_SHORT_TEE
    return raw


def map_mercari_category_path(category: str, listing: dict | None = None) -> str:
    """Map a Vendoo/listing category onto a selectable Mercari path."""
    listing = listing if isinstance(listing, dict) else {}
    raw = (category or "").strip() or str(listing.get("category_path") or "").strip()
    specifics = listing.get("mercari_specifics")
    if isinstance(specifics, dict):
        explicit = specifics.get("category_path") or specifics.get("categoryPath")
        explicit_path = ""
        if isinstance(explicit, list):
            explicit_path = " > ".join(str(part).strip() for part in explicit if str(part).strip())
        elif isinstance(explicit, str):
            explicit_path = explicit.strip()
        if explicit_path and not _stale_top_leaf(explicit_path, listing):
            return explicit_path

    if _MERCARI_ROOT_RE.search(raw) and not _stale_top_leaf(raw, listing):
        return raw
    if _NON_TOP_RE.search(_path_leaf(raw)) or _non_top_listing(listing):
        return raw

    # Garment cues only — "Tops & blouses > T-shirts" contains both words and
    # would otherwise answer the question being asked of the listing.
    haystack = (
        f"{_listing_garment_haystack(listing)} {_listing_style(listing)}"
    )
    gender = _listing_gender(listing, raw)
    is_women = gender == "women"
    if gender is None:
        is_women = bool(_WOMEN_RE.search(f"{raw} {haystack}"))
    kind = _top_kind(haystack)
    if is_women and kind:
        leaf = _women_top_leaf("mercari", kind, haystack)
        if leaf:
            return leaf
    if is_women and _TOP_ITEM_RE.search(haystack):
        return MERCARI_WOMEN_TEE
    return raw


def map_etsy_category_path(category: str, listing: dict | None = None) -> str:
    """Map a Vendoo/listing category onto a selectable Etsy path."""
    listing = listing if isinstance(listing, dict) else {}
    raw = (category or "").strip() or str(listing.get("category_path") or "").strip()
    specifics = listing.get("etsy_specifics")
    if isinstance(specifics, dict):
        explicit = specifics.get("category_path") or specifics.get("categoryPath")
        explicit_path = ""
        if isinstance(explicit, list):
            explicit_path = " > ".join(str(part).strip() for part in explicit if str(part).strip())
        elif isinstance(explicit, str):
            explicit_path = explicit.strip()
        if explicit_path and not _stale_etsy_path(explicit_path, listing):
            return explicit_path

    if _ETSY_ROOT_RE.search(raw) and not _stale_etsy_path(raw, listing):
        return raw
    if _NON_TOP_RE.search(_path_leaf(raw)) or _non_top_listing(listing):
        return raw

    # Score garment cues only — never the marketplace path. "Tops & Tees > Tunics"
    # contains "Tees" and would otherwise block blouse / button-up detection.
    haystack = (
        f"{_listing_text(listing)} {listing.get('description') or ''} "
        f"{_listing_style(listing)}"
    )
    gender = _listing_gender(listing, raw)
    is_women = gender == "women"
    if gender is None:
        is_women = bool(_WOMEN_RE.search(f"{raw} {haystack}"))
    kind = _top_kind(haystack)
    if is_women and kind:
        leaf = _women_top_leaf("etsy", kind, haystack)
        if leaf:
            return leaf
    if is_women and _TOP_ITEM_RE.search(haystack):
        return ETSY_WOMEN_TEE
    return raw


def map_depop_category_path(category: str, listing: dict | None = None) -> str:
    """Map a Vendoo/listing category onto a selectable Depop path."""
    listing = listing if isinstance(listing, dict) else {}
    raw = (category or "").strip() or str(listing.get("category_path") or "").strip()
    specifics = listing.get("depop_specifics")
    if isinstance(specifics, dict):
        explicit = specifics.get("category_path") or specifics.get("categoryPath")
        explicit_path = ""
        if isinstance(explicit, list):
            explicit_path = " > ".join(str(part).strip() for part in explicit if str(part).strip())
        elif isinstance(explicit, str):
            explicit_path = explicit.strip()
        if explicit_path and not _stale_top_leaf(explicit_path, listing):
            return explicit_path

    if _DEPOP_ROOT_RE.search(raw) and not _stale_top_leaf(raw, listing):
        return raw
    if _NON_TOP_RE.search(_path_leaf(raw)) or _non_top_listing(listing):
        return raw

    haystack = f"{_listing_garment_haystack(listing)} {_listing_style(listing)}"
    gender = _listing_gender(listing, raw)
    is_women = gender == "women"
    if gender is None:
        is_women = bool(_WOMEN_RE.search(f"{raw} {haystack}"))
    # Depop splits the two: a button-up is a Shirt there, a blouse a Blouse.
    kind = _top_kind(haystack)
    if is_women and kind:
        leaf = _women_top_leaf("depop", kind, haystack)
        if leaf:
            return leaf
    if is_women and _TOP_ITEM_RE.search(haystack):
        return DEPOP_WOMEN_TEE
    return raw


CATEGORY_PATH_MAPPERS = {
    "poshmark": map_poshmark_category_path,
    "mercari": map_mercari_category_path,
    "etsy": map_etsy_category_path,
    "depop": map_depop_category_path,
}


def map_marketplace_category_path(marketplace: str, category: str, listing: dict | None = None) -> str:
    """Remap one marketplace's category leaf; unmapped marketplaces pass through."""
    mapper = CATEGORY_PATH_MAPPERS.get(str(marketplace or "").strip().lower())
    return mapper(category, listing) if mapper else category


class RegistryService:
    def __init__(self, db: Session):
        self._repo = RegistryRepo(db)

    def normalize_value(
        self,
        marketplace: str,
        field_label: str,
        value: str,
        category_path: str | None = None,
    ) -> tuple[str, bool, str]:
        valid = self._repo.get_valid_options(marketplace, field_label, category_path)
        if not valid:
            return (value, True, "")

        trimmed = value.strip()
        if trimmed == "":
            return (value, True, "")

        if trimmed in valid:
            return (trimmed, True, "")

        lower = trimmed.lower()
        for v in valid:
            if v.lower() == lower:
                return (v, True, "")

        norm = _tokenize(lower)
        for v in valid:
            if _tokenize(v.lower()) == norm:
                return (v, True, "")

        canonical = CANONICAL_DEFAULTS.get(marketplace, {}).get(field_label.lower(), "")
        if canonical:
            return (canonical, False, f"Replaced '{trimmed}' with canonical default '{canonical}'")

        return (value, False, f"'{trimmed}' not in known options: {valid[:5]}...")

    def normalize_category(self, marketplace: str, category: str, listing: dict | None = None) -> tuple[str, bool]:
        trimmed = (category or "").strip()
        if marketplace != "general":
            mapped = CATEGORY_NORMALIZATIONS.get(marketplace, {}).get(trimmed.lower())
            if mapped:
                return (mapped, True)
            return (trimmed, False)
        mapped = map_vendoo_category_path(trimmed, listing)
        return (mapped, mapped != trimmed)

    def validate_dropdown_fields(
        self,
        listing: dict,
        marketplace: str,
        category_path: str | None = None,
    ) -> list[dict]:
        warnings = []
        specifics = listing.get(f"{marketplace}_specifics", {}) or {}
        if not isinstance(specifics, dict):
            return warnings

        for field, value in specifics.items():
            if not isinstance(value, str) or not value:
                continue
            normalized, ok, msg = self.normalize_value(
                marketplace, field, value, category_path,
            )
            if not ok:
                specifics[field] = normalized
                warnings.append({
                    "marketplace": marketplace,
                    "field": field,
                    "original": value,
                    "corrected": normalized,
                    "message": msg,
                })

        if warnings:
            listing[f"{marketplace}_specifics"] = specifics
        return warnings

    def build_context(
        self,
        marketplace: str,
        category_path: str | None = None,
    ) -> str:
        return self._repo.get_registry_context(marketplace, category_path)

    def generation_context(self, category_path: str | None = None) -> str:
        lines = [
            "Learned marketplace fields from previous fills. Include a value for every "
            "field that applies to this item's category. Use a real value, or Does Not Apply "
            "when the field is on the form but does not apply to this item.",
            "When a field lists allowed values, copy one of them exactly — Vendoo rejects "
            "anything that is not on the list.",
            "",
        ]
        grouped: dict[tuple[str, str], list[str]] = {}
        for marketplace in LEARNED_MARKETPLACES:
            for entry in self._repo.list_fields(
                marketplace, category_path, all_categories=category_path is None
            ):
                label = entry.normalized_label
                if not is_learned_listing_field(marketplace, label):
                    continue
                json_key = label_to_json_key(label)
                if not json_key:
                    continue
                display = json_key if json_key == label else f"{json_key} ({label})"
                if entry.known_options:
                    options = sorted(entry.known_options)[:MAX_PROMPT_OPTIONS]
                    listed = "; ".join(options)
                    if len(entry.known_options) > MAX_PROMPT_OPTIONS:
                        listed += "; …"
                    display += f" — one of: {listed}"
                cat = entry.category_path or ""
                grouped.setdefault((marketplace, cat), []).append(display)

        if not grouped:
            return ""

        for (marketplace, cat), fields in grouped.items():
            heading = f"## {marketplace}"
            if cat:
                heading += f" — {cat}"
            lines.append(heading)
            seen = set()
            for field in fields:
                if field in seen:
                    continue
                seen.add(field)
                lines.append(f"- {field}")
            lines.append("")
        return "\n".join(lines).strip()

    def merge_learned_fields(self, listing: dict) -> list[str]:
        """Add empty keys for learned item fields missing from the listing. Returns JSON paths added."""
        if not isinstance(listing, dict):
            return []

        category_path = listing.get("category_path") or None
        added: list[str] = []
        for marketplace in LEARNED_MARKETPLACES:
            entries = self._repo.list_fields(marketplace, category_path)
            if not entries:
                continue
            specifics_key = f"{marketplace}_specifics"
            specifics = listing.get(specifics_key)
            if not isinstance(specifics, dict):
                specifics = {}
                listing[specifics_key] = specifics

            for entry in entries:
                label = entry.normalized_label
                if not is_learned_listing_field(marketplace, label):
                    continue
                json_key = label_to_json_key(label)
                if not json_key:
                    continue
                if json_key in specifics:
                    continue
                specifics[json_key] = ""
                added.append(f"{specifics_key}.{json_key}")
            listing[specifics_key] = specifics
        return added


def is_learned_listing_field(marketplace: str, field_label: str) -> bool:
    label = _normalize_label(field_label)
    if not label or marketplace not in LEARNED_MARKETPLACES:
        return False
    if label in SELLER_SETTING_LABELS or label in ROOT_FIELD_LABELS:
        return False
    if is_account_managed_field(marketplace, label):
        return False
    return True


def _label_words(field_label: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(field_label or ""))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def is_account_managed_field(marketplace: str, field_label: str) -> bool:
    """True for shipping/policy rows the seller already set in marketplace settings.

    Policies are fixed everywhere. Shipping is per item only on Depop (parcel size)
    and Mercari (shipping label), so the filler leaves shipping alone on every other
    form — including the general form's marketplace-agnostic shipping rows. General
    weight and package dimensions are not matched here: Depop's parcel tier is
    derived from them.
    """
    words = _label_words(field_label)
    if not words:
        return False
    if _POLICY_LABEL_RE.search(words):
        return True
    if str(marketplace or "").strip().lower() in ITEM_SHIPPING_MARKETPLACES:
        return False
    return bool(_SHIPPING_LABEL_RE.search(words))


def label_to_json_key(field_label: str) -> str:
    label = _normalize_label(field_label)
    if not label:
        return ""
    if label in LABEL_TO_JSON_KEY:
        return LABEL_TO_JSON_KEY[label]
    parts = label.replace("/", " ").replace("-", " ").split()
    if not parts:
        return ""
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def _has_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _tokenize(text: str) -> str:
    return " ".join(text.replace("-", " ").replace("&", " ").replace("/", " ").split())
