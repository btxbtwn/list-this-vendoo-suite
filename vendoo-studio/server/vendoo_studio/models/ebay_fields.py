"""eBay item specifics: required keys, season inference, and category optional defaults."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from vendoo_studio.models.listing_values import (
    DNA_VALUE,
    collapse_option,
    dropdown_field_options,
    evidence_unknown,
    infer_known_option,
    infer_known_options,
    normalized_option_key,
    text_value,
)

REQUIRED_EBAY_KEYS = ("type", "department", "sizeType", "size", "brand")
EBAY_KEY_ALIASES = {
    "Size": "size",
    "Department": "department",
    "Size Type": "sizeType",
    "Type": "type",
    "Brand": "brand",
    "Season": "season",
    "Features": "features",
    "feature": "features",
    "qty": "unitQuantity",
}
VALID_EBAY_SEASONS = frozenset({"Spring", "Summer", "Fall", "Winter"})
# Stable order for scoring ties and packing multi-select values.
DEFAULT_EBAY_SEASONS = ("Spring", "Summer", "Fall", "Winter")
# Gap-fill often writes Does Not Apply; Season must always be a calendar season.
EBAY_SEASON_CLEAR = frozenset({
    "does not apply",
    "n/a",
    "na",
    "n.a",
    "n.a.",
    "none",
    "unknown",
    "-",
    "--",
    "d",
})
EBAY_SEASON_ALL_YEAR = frozenset({
    "all season",
    "all-season",
    "all seasons",
    "year round",
    "year-round",
})
# Explicit season words in copy still win; otherwise cues below pick one.
EBAY_SEASON_CUES: dict[str, tuple[str, ...]] = {
    "Winter": (
        r"\bwinter\b", r"\bwool\b", r"\bfleece\b", r"\bcashmere\b", r"\bcoat\b",
        r"\bparka\b", r"\bpuffer\b", r"\bdown\b", r"\bthermal\b", r"\bhoodie\b",
        r"\bsweater\b", r"\bpullover\b", r"\bcable\b", r"\bknit\b", r"\bcardigan\b",
        r"\bheavyweight\b", r"\binsulated\b", r"\bboot(?:s)?\b", r"\bsnow\b",
    ),
    "Summer": (
        r"\bsummer\b", r"\blinen\b", r"\btank\b", r"\bsleeveless\b", r"\bshorts?\b",
        r"\bsundress\b", r"\bcami\b", r"\bswim\b", r"\bbikini\b", r"\bshort[\s-]*sleeve\b",
        r"\bcrop(?:ped)?\s*top\b", r"\btropical\b", r"\bbeach\b", r"\bv\-?neck\s*tee\b",
        r"\bt[\s-]?shirt\b", r"\btee\b", r"\bpolo\b",
    ),
    "Fall": (
        r"\bfall\b", r"\bautumn\b", r"\bflannel\b", r"\bcorduroy\b", r"\btweed\b",
        r"\blight[\s-]*jacket\b", r"\bdenim\s*jacket\b", r"\bshacket\b",
        r"\bmidweight\b", r"\blayering\b",
    ),
    "Spring": (
        r"\bspring\b", r"\bfloral\b", r"\bflower\b", r"\bblossom\b", r"\bpastel\b",
        r"\bblouse\b", r"\bruched\b", r"\blightweight\b", r"\bchiffon\b",
        r"\bsatin\b", r"\bsilk\b", r"\btrench\b",
    ),
}
# Mirrors vendoo-studio/src/marketplaceFields.ts EBAY_CATEGORY_OPTIONALS (minus seller store UI).
EBAY_CATEGORY_OPTIONAL_KEYS = (
    "accents",
    "character",
    "closure",
    "countryOfOrigin",
    "fabricType",
    "fabricWeight",
    "features",
    "fit",
    "garmentCare",
    "handmade",
    "mpn",
    "material",
    "neckline",
    "occasion",
    "pattern",
    "personalize",
    "season",
    "sleeveLength",
    "sleeveType",
    "strapType",
    "style",
    "theme",
    "unitQuantity",
    "unitType",
    "vintage",
    "upc",
)
# eBay's Condition Description is the same line on every listing this seller
# makes — the photos carry the condition, so it never varies per item.
EBAY_CONDITION_DESCRIPTION = "SEE PHOTOS FOR CONDITION AND MEASUREMENTS"
EBAY_OPTIONAL_FIXED_DEFAULTS = {
    "handmade": "No",
    "personalize": "No",
    "unitQuantity": "1",
    "unitType": "Unit",
    "vintage": "No",
}
EBAY_OPTIONAL_INFER_FALLBACKS = {
    "pattern": "Solid",
    "occasion": "Casual",
    "fit": "Regular",
    "style": "Basic",
    "closure": "Pullover",
    "neckline": "Crew Neck",
    "features": "Lightweight",
}
EBAY_OPTIONAL_ALWAYS_DEFAULTS = {**EBAY_OPTIONAL_FIXED_DEFAULTS, **EBAY_OPTIONAL_INFER_FALLBACKS}
EBAY_OCCASION_OPTIONS = (
    "Casual", "Workwear", "Formal", "Party/Cocktail", "Activewear",
    "Travel", "Everyday", "Business",
)
EBAY_APPAREL_CUES = {
    "pattern": {
        "Floral": (r"\bfloral\b", r"\bflower(?:ed|s)?\b"),
        "Striped": (r"\bstripe[ds]?\b",),
        "Plaid": (r"\bplaid\b",),
        "Graphic Print": (r"\bgraphic\b", r"\blogo\b"),
        "Solid": (r"\bsolid\b", r"\bplain\b"),
    },
    "fit": {
        "Relaxed": (r"\brelaxed\b", r"\boversized\b"),
        "Slim": (r"\bslim\b",),
        "Athletic": (r"\bathletic\b", r"\bworkout\b"),
        "Regular": (r"\bregular\b",),
        "Classic": (r"\bclassic\b",),
    },
    "style": {
        "Cropped": (r"\bcrop(?:ped)?\b",),
        "Ringer": (r"\bringer\b",),
        "Basic": (r"\bbasic\b", r"\btee\b", r"\bt[\s-]?shirt\b"),
    },
    "neckline": {
        "V-Neck": (r"\bv[\s-]*neck\b",),
        "Crew Neck": (r"\bcrew(?:\s*neck)?\b",),
        "Henley": (r"\bhenley\b",),
        "Collared": (r"\bcollar(?:ed)?\b", r"\bpolo\b"),
    },
    "closure": {
        "Pullover": (r"\bpullover\b", r"\btee\b", r"\bt[\s-]?shirt\b"),
        "Button": (r"\bbutton(?:[\s-]*up|[\s-]*down)?\b",),
        "Zip": (r"\bzip(?:per|[\s-]*up)?\b",),
    },
    "features": {
        "Lightweight": (r"\blightweight\b", r"\btee\b", r"\bt[\s-]?shirt\b", r"\bblouse\b"),
        "Heavyweight": (r"\bheavyweight\b",),
        "Hooded": (r"\bhood(?:ed|ie)?\b",),
        "Pockets": (r"\bpocket(?:s)?\b",),
        "Stretch": (r"\bstretch\b",),
        "Oversized": (r"\boversized\b",),
    },
    "occasion": {
        "Casual": (r"\bcasual\b", r"\beveryday\b", r"\btee\b"),
        "Workwear": (r"\bworkwear\b", r"\boffice\b"),
        "Formal": (r"\bformal\b", r"\bwedding\b"),
        "Party/Cocktail": (r"\bparty\b", r"\bcocktail\b"),
        "Activewear": (r"\bactivewear\b", r"\bworkout\b", r"\bgym\b"),
        "Travel": (r"\btravel\b", r"\bvacation\b"),
    },
}
# Only these may be Does Not Apply when empty — everything else must be a real value.
# Fabric Weight is numeric on eBay (must be > 0); DNA is rejected at list time.
EBAY_OPTIONAL_DNA_KEYS = frozenset({
    "mpn",
    "upc",
    "character",
    "characterFamily",
    "strapType",
    "theme",
    "performanceActivity",
    "accents",
    "countryOfOrigin",
    "sleeveType",
    "personalizationInstructions",
})
# Tag-evidence fields: blank stays a warning (never invent), not DNA.
# Fabric Weight: omit when unknown — eBay rejects "Does Not Apply" and requires a number > 0.
EBAY_OPTIONAL_EVIDENCE_KEYS = frozenset({"material", "fabricType", "garmentCare", "fabricWeight"})
# Free-text / DNA / Features-chip tokens that must never be submitted as Fabric Weight.
# Leave blank unless a real numeric oz/gsm value is evidenced — never invent.
EBAY_FABRIC_WEIGHT_CLEAR = frozenset({
    "does not apply",
    "n/a",
    "na",
    "n.a",
    "n.a.",
    "none",
    "unknown",
    "-",
    "--",
    "d",
    "lightweight",
    "light weight",
    "light-weight",
    "light",
    "midweight",
    "mid weight",
    "mid-weight",
    "medium",
    "medium weight",
    "medium-weight",
    "heavyweight",
    "heavy weight",
    "heavy-weight",
    "heavy",
})
EBAY_FABRIC_WEIGHT_RE = re.compile(
    r"^(\d+(?:\.\d)?)\s*(?:oz(?:/?\s*yd(?:\^?2|²)?)?|g/?m(?:\^?2|²)?|gsm)?$",
    re.I,
)

# Lookup keys (field_lookup_key form) for apparel optionals that must not silent-skip.
EBAY_OPTIONAL_MUST_FILL_LOOKUPS = frozenset({
    "accents",
    "character",
    "closure",
    "country of origin",
    "fabric type",
    "fabric weight",
    "features",
    "fit",
    "garment care",
    "handmade",
    "mpn",
    "material",
    "neckline",
    "occasion",
    "pattern",
    "personalize",
    "season",
    "sleeve length",
    "sleeve type",
    "strap type",
    "style",
    "theme",
    "unit quantity",
    "unit type",
    "vintage",
    "upc",
})
EBAY_OPTIONAL_DNA_LOOKUPS = frozenset({
    "mpn",
    "upc",
    "character",
    "character family",
    "strap type",
    "theme",
    "performance activity",
    "accents",
    "country of origin",
    "sleeve type",
    "personalization instructions",
})

# Mirrors vendoo-studio/src/marketplaceFields.ts ETSY_CATEGORY_OPTIONALS (+ fabricPattern alias).


def ebay_season_parts(value: Any) -> list[str]:
    """Split Season chips / comma lists into individual tokens."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        parts: list[str] = []
        for item in value:
            parts.extend(ebay_season_parts(item))
        return parts
    text = text_value(value)
    if not text:
        return []
    folded = text.casefold()
    if folded in EBAY_SEASON_CLEAR or folded in EBAY_SEASON_ALL_YEAR:
        return [text]
    if re.fullmatch(r"all[\s-]*seasons?", folded):
        return [text]
    if not re.search(r"[,;/|]", text):
        return [text]
    return [part.strip() for part in re.split(r"[,;/|]+", text) if part.strip()]


def exact_ebay_season(part: str) -> str | None:
    needle = collapse_option(part)
    key = normalized_option_key(part)
    for option in VALID_EBAY_SEASONS:
        if needle == collapse_option(option) or key == normalized_option_key(option):
            return option
    return None


def ebay_season_haystack(listing: dict | None, ebay: dict | None = None) -> str:
    listing = listing if isinstance(listing, dict) else {}
    ebay = ebay if isinstance(ebay, dict) else {}
    if not ebay:
        raw = listing.get("ebay_specifics")
        ebay = raw if isinstance(raw, dict) else {}
    chunks = [
        listing.get("title"),
        listing.get("description"),
        listing.get("category_path"),
        listing.get("type"),
        listing.get("primaryColor"),
        listing.get("color"),
        ebay.get("type"),
        ebay.get("Type"),
        ebay.get("material"),
        ebay.get("fabricType"),
        ebay.get("sleeveLength"),
        ebay.get("style"),
        ebay.get("theme"),
        ebay.get("features"),
        ebay.get("occasion"),
    ]
    parts: list[str] = []
    for chunk in chunks:
        if chunk is None or chunk == "":
            continue
        if isinstance(chunk, (list, tuple, set)):
            parts.extend(str(item) for item in chunk if item is not None and item != "")
        else:
            parts.append(str(chunk))
    return " ".join(parts).casefold()


def infer_ebay_season(listing: dict | None = None, *, ebay: dict | None = None) -> str:
    """Pick one Spring/Summer/Fall/Winter from listing cues (never DNA / all-year)."""
    hay = ebay_season_haystack(listing, ebay)
    scores = {name: 0 for name in DEFAULT_EBAY_SEASONS}
    for season, patterns in EBAY_SEASON_CUES.items():
        for pattern in patterns:
            if re.search(pattern, hay, flags=re.I):
                scores[season] += 1
    best = max(DEFAULT_EBAY_SEASONS, key=lambda name: (scores[name], -DEFAULT_EBAY_SEASONS.index(name)))
    if scores[best] > 0:
        return best
    # Lightweight apparel defaults to Summer; cold-weather garments to Winter.
    if re.search(r"\b(?:coat|parka|puffer|sweater|hoodie|fleece|wool|boot)\b", hay):
        return "Winter"
    return "Summer"


def _append_ebay_seasons(kept: list[str], seasons: Iterable[str]) -> bool:
    changed = False
    for season in seasons:
        canon = exact_ebay_season(str(season)) or (
            str(season) if str(season) in VALID_EBAY_SEASONS else None
        )
        if not canon:
            continue
        if canon not in kept:
            kept.append(canon)
            changed = True
    return changed


def _pack_ebay_seasons(kept: list[str]) -> Any:
    if not kept:
        return "Summer"
    if len(kept) == 1:
        return kept[0]
    order = {name: index for index, name in enumerate(DEFAULT_EBAY_SEASONS)}
    return sorted(kept, key=lambda name: order.get(name, 99))


def normalize_ebay_season_value(
    value: Any,
    *,
    listing: dict | None = None,
    ebay: dict | None = None,
) -> tuple[Any, bool]:
    """Force Season to real calendar chips; infer one when DNA / blank / all-year."""
    inferred = infer_ebay_season(listing, ebay=ebay)
    parts = ebay_season_parts(value)
    if not parts:
        return inferred, True

    kept: list[str] = []
    changed = False
    needs_inference = False
    for part in parts:
        folded = part.casefold()
        if folded in EBAY_SEASON_CLEAR or folded in EBAY_SEASON_ALL_YEAR or re.fullmatch(r"all[\s-]*seasons?", folded):
            needs_inference = True
            changed = True
            continue
        canon = exact_ebay_season(part)
        if canon:
            if canon not in kept:
                kept.append(canon)
            if part != canon:
                changed = True
            continue
        # Leave unrecognized tokens so validate_listing can still surface them.
        if part not in kept:
            kept.append(part)

    valid = [part for part in kept if exact_ebay_season(part)]
    invalid = [part for part in kept if exact_ebay_season(part) is None]
    if invalid and not valid:
        # Pure junk like "S" — keep for validation error rather than inventing seasons.
        normalized: Any = kept[0] if len(kept) == 1 else kept
        return normalized, normalized != value
    if needs_inference and not valid:
        return inferred, True
    if not valid:
        return inferred, True
    if invalid:
        changed = True
    # Prefer a single inferred season when the only signal was all-year/DNA plus
    # no explicit calendar chip; otherwise keep explicit multi-select chips.
    packed = _pack_ebay_seasons(valid)
    if packed != value:
        changed = True
    return packed, changed


def ebay_key_fold(text: Any) -> str:
    """"Fabric Weight", "fabric_weight" and "fabricWeight" all name one field."""
    return re.sub(r"[^a-z0-9]", "", str(text or "").casefold())


def ebay_optional_keys(block: Any, key: str) -> list[str]:
    """Every spelling of ``key`` a specifics block holds, in its own order.

    A value written from a form label lands under "Fabric Weight", one written
    from the listing JSON under "fabricWeight". Both are the same eBay field
    and both reach the form, so both have to be read and rewritten.
    """
    if not isinstance(block, dict):
        return []
    folded = ebay_key_fold(key)
    return [name for name in block if ebay_key_fold(name) == folded]


def ebay_optional_raw(ebay: dict, key: str) -> Any:
    """Read an optional from flat ebay_specifics or nested category_specifics."""
    if not isinstance(ebay, dict):
        return None
    if key in ebay:
        return ebay.get(key)
    title = key[:1].upper() + key[1:] if key else key
    if title in ebay:
        return ebay.get(title)
    nested = ebay.get("category_specifics")
    if isinstance(nested, dict):
        if key in nested:
            return nested.get(key)
        if title in nested:
            return nested.get(title)
    for name in ebay_optional_keys(ebay, key):
        return ebay.get(name)
    for name in ebay_optional_keys(nested, key):
        return nested.get(name)
    return None


def ebay_optional_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        text = value.strip()
        if not text or text == "----" or text.casefold() in {"select", "n/a", "na"}:
            return True
    if isinstance(value, (list, tuple)) and not value:
        return True
    return False


def _infer_ebay_sleeve_length(listing: dict | None, ebay: dict | None) -> str:
    hay = ebay_season_haystack(listing, ebay)
    if re.search(r"\b(?:sleeveless|tank|cami|halter|strapless)\b", hay):
        return "Sleeveless"
    if re.search(r"\b(?:3[\s/]*4|three[\s-]*quarter)\s*sleeve\b", hay):
        return "3/4 Sleeve"
    if re.search(r"\b(?:long[\s-]*sleeve|ls)\b", hay) or re.search(
        r"\b(?:sweater|hoodie|coat|parka|cardigan|fleece)\b", hay
    ):
        return "Long Sleeve"
    if re.search(r"\b(?:cap[\s-]*sleeve)\b", hay):
        return "Cap Sleeve"
    if re.search(r"\b(?:short[\s-]*sleeve|ss|tee|t[\s-]?shirt|polo|blouse)\b", hay):
        return "Short Sleeve"
    return "Short Sleeve"


def _fabric_weight_word_key(text: str) -> str:
    return re.sub(r"[\s\-]+", " ", text.casefold()).strip()


def normalize_ebay_fabric_weight(value: Any) -> tuple[Any, bool]:
    """Keep an evidenced numeric oz/gsm value; clear DNA, Features chips, and other junk."""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return "", False
    if ebay_optional_blank(value):
        return "", True
    text = text_value(value)
    if _fabric_weight_word_key(text) in EBAY_FABRIC_WEIGHT_CLEAR:
        return "", True
    match = EBAY_FABRIC_WEIGHT_RE.fullmatch(text)
    if match:
        num = match.group(1)
        if float(num) > 0:
            return num, num != text
    # Non-numeric junk must not reach eBay — leave blank rather than invent.
    return "", True


def _infer_ebay_fabric_type(listing: dict | None, ebay: dict | None) -> str | None:
    ebay = ebay if isinstance(ebay, dict) else {}
    material = text_value(ebay_optional_raw(ebay, "material") or (listing or {}).get("material"))
    if material:
        first = material.split(",")[0].strip()
        if first:
            return first
    hay = ebay_season_haystack(listing, ebay)
    for pattern, label in (
        (r"\bdenim\b", "Denim"),
        (r"\bfleece\b", "Fleece"),
        (r"\bflannel\b", "Flannel"),
        (r"\bcorduroy\b", "Corduroy"),
        (r"\bsatin\b", "Satin"),
        (r"\bchiffon\b", "Chiffon"),
        (r"\blinen\b", "Linen"),
        (r"\bknit\b", "Knit"),
        (r"\bjersey\b", "Jersey"),
        (r"\bcotton\b", "Cotton"),
    ):
        if re.search(pattern, hay):
            return label
    return None


def ensure_ebay_category_optionals(listing: dict) -> bool:
    """Fill eBay Show-Optional-Fields rows: defaults, DNA only when N/A, infer season/sleeve."""
    if not isinstance(listing, dict):
        return False
    raw = listing.get("ebay_specifics")
    if not isinstance(raw, dict):
        return False
    ebay = dict(raw)
    changed = False

    def set_key(key: str, value: Any) -> None:
        nonlocal ebay, changed
        if ebay_optional_blank(ebay_optional_raw(ebay, key)):
            ebay[key] = value
            nested = ebay.get("category_specifics")
            if isinstance(nested, dict) and key in nested and ebay_optional_blank(nested.get(key)):
                nested = dict(nested)
                nested[key] = value
                ebay["category_specifics"] = nested
            changed = True

    for key, default in EBAY_OPTIONAL_FIXED_DEFAULTS.items():
        set_key(key, default)

    hay = ebay_season_haystack(listing, ebay)
    field_option_names = {
        "pattern": ("Pattern", "pattern"),
        "fit": ("fit", "Fit"),
        "style": ("Style", "style"),
        "neckline": ("Neckline", "neckline"),
        "closure": ("closure", "Closure"),
        "features": ("Features", "features"),
    }
    for key, fallback in EBAY_OPTIONAL_INFER_FALLBACKS.items():
        if not ebay_optional_blank(ebay_optional_raw(ebay, key)):
            continue
        if key == "occasion":
            options = list(EBAY_OCCASION_OPTIONS)
        else:
            options = dropdown_field_options("ebay", *field_option_names.get(key, (key,))) or [fallback]
        cues = EBAY_APPAREL_CUES.get(key)
        if key == "features":
            picked = infer_known_options(hay, options, cues=cues, fallbacks=(fallback,), limit=1)
            value = picked[0] if picked else fallback
        else:
            value = infer_known_option(hay, options, cues=cues, fallback=fallback) or fallback
        set_key(key, value)


    # Condition Description is fixed, not a default: whatever a model wrote or
    # an import carried over is replaced.
    if ebay.get("conditionDescription") != EBAY_CONDITION_DESCRIPTION:
        ebay["conditionDescription"] = EBAY_CONDITION_DESCRIPTION
        changed = True
    nested = ebay.get("category_specifics")
    if isinstance(nested, dict) and nested.get("conditionDescription") not in (
        None, EBAY_CONDITION_DESCRIPTION,
    ):
        nested = dict(nested)
        nested["conditionDescription"] = EBAY_CONDITION_DESCRIPTION
        ebay["category_specifics"] = nested
        changed = True

    care_unknown = evidence_unknown(
        text_value((listing or {}).get("description")),
        "care tag is not shown",
        "garment care",
        "unverified",
    ) or any(
        token in text_value((listing or {}).get("description")).casefold()
        for token in ("garment care is unknown", "care is unknown", "care tag is not shown")
    )
    if not care_unknown and ebay_optional_blank(ebay_optional_raw(ebay, "garmentCare")):
        set_key("garmentCare", "Machine Washable")

    if ebay_optional_blank(ebay_optional_raw(ebay, "season")) and ebay_optional_blank(
        ebay_optional_raw(ebay, "Season")
    ):
        set_key("season", infer_ebay_season(listing, ebay=ebay))
    else:
        normalized, season_changed = normalize_ebay_season_value(
            ebay_optional_raw(ebay, "season") or ebay_optional_raw(ebay, "Season"),
            listing=listing,
            ebay=ebay,
        )
        if season_changed or "Season" in ebay:
            ebay["season"] = normalized
            ebay.pop("Season", None)
            changed = True

    if ebay_optional_blank(ebay_optional_raw(ebay, "sleeveLength")):
        set_key("sleeveLength", _infer_ebay_sleeve_length(listing, ebay))

    fabric = _infer_ebay_fabric_type(listing, ebay)
    if fabric and ebay_optional_blank(ebay_optional_raw(ebay, "fabricType")):
        set_key("fabricType", fabric)

    # Vintage follows the item's era, never style words: a "Y2K" or "vintage-style"
    # tee made in the 2010s is not vintage. A modern Etsy When Made forces No.
    from vendoo_studio.models.etsy_fields import etsy_when_is_modern, etsy_when_raw

    etsy = listing.get("etsy_specifics")
    when_made = etsy_when_raw(etsy if isinstance(etsy, dict) else {}, {**listing, "ebay_specifics": ebay})
    if when_made and etsy_when_is_modern(when_made):
        if text_value(ebay_optional_raw(ebay, "vintage")).casefold() != "no":
            ebay["vintage"] = "No"
            ebay.pop("Vintage", None)
            nested = ebay.get("category_specifics")
            if isinstance(nested, dict) and ({"vintage", "Vintage"} & nested.keys()):
                ebay["category_specifics"] = {
                    **{k: v for k, v in nested.items() if k != "Vintage"},
                    "vintage": "No",
                }
            changed = True

    for key in EBAY_OPTIONAL_DNA_KEYS:
        if key == "personalizationInstructions":
            personalize = text_value(ebay_optional_raw(ebay, "personalize") or "No")
            if personalize.casefold() == "yes":
                continue
        if ebay_optional_blank(ebay_optional_raw(ebay, key)):
            set_key(key, DNA_VALUE)

    # Fabric Weight: keep evidenced numerics only; clear DNA / Lightweight / other junk.
    # Never invent a weight — blank when unknown.
    raw_weight = ebay_optional_raw(ebay, "fabricWeight")
    if not ebay_optional_blank(raw_weight):
        normalized_weight, weight_changed = normalize_ebay_fabric_weight(raw_weight)
        if weight_changed or text_value(normalized_weight) != text_value(raw_weight):
            # Rewrite every spelling the listing holds — a word left under
            # "Fabric Weight" reaches the form just as one under "fabricWeight".
            for name in ebay_optional_keys(ebay, "fabricWeight") or ["fabricWeight"]:
                ebay[name] = normalized_weight
            nested = ebay.get("category_specifics")
            nested_keys = ebay_optional_keys(nested, "fabricWeight")
            if nested_keys:
                nested = {**nested, **{name: normalized_weight for name in nested_keys}}
                ebay["category_specifics"] = nested
            changed = True

    # Material: copy fabricType fiber when material empty and fabric looks like a fiber.
    if ebay_optional_blank(ebay_optional_raw(ebay, "material")):
        fabric_val = text_value(ebay_optional_raw(ebay, "fabricType"))
        if fabric_val and fabric_val.casefold() not in {
            "knit", "jersey", "woven", "canvas", "twill", "microfiber",
        }:
            set_key("material", fabric_val)

    if changed:
        listing["ebay_specifics"] = ebay
    return changed


def promote_required_ebay_specifics(listing: dict) -> bool:
    """Lift required eBay keys out of category_specifics — the filler reads them flat."""
    ebay = listing.get("ebay_specifics")
    if not isinstance(ebay, dict):
        return False
    nested = ebay.get("category_specifics")
    if not isinstance(nested, dict):
        return False
    changed = False
    for key in REQUIRED_EBAY_KEYS:
        if not ebay_optional_blank(ebay.get(key)):
            continue
        value = nested.get(key)
        if ebay_optional_blank(value):
            continue
        ebay[key] = value
        changed = True
    return changed
