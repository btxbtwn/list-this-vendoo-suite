from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

from pydantic import BaseModel, Field, ValidationError

from vendoo_studio.config import skills_dir
from vendoo_studio.models.schema import (
    PACKAGE_DIMS_PATTERN,
    VALID_DEPOP_AGE,
    VALID_DEPOP_MATERIAL,
    VALID_DEPOP_OCCASION,
    VALID_DEPOP_SOURCE,
    VALID_DEPOP_STYLE,
    ListingSchema,
    _scalar_text,
)
from vendoo_studio.services.marketplaces import FILLABLE_MARKETPLACES, get_selected_marketplaces


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
EBAY_OPTIONAL_ALWAYS_DEFAULTS = {
    "handmade": "No",
    "personalize": "No",
    "unitQuantity": "1",
    "unitType": "Unit",
    "vintage": "No",
    "pattern": "Solid",
    "occasion": "Casual",
    "fit": "Regular",
    "style": "Basic",
    "closure": "Pullover",
    "neckline": "Crew Neck",
    "features": "Lightweight",
}
# Only these may be Does Not Apply when empty — everything else must be a real value.
EBAY_OPTIONAL_DNA_KEYS = frozenset({
    "mpn",
    "upc",
    "character",
    "characterFamily",
    "strapType",
    "fabricWeight",
    "theme",
    "performanceActivity",
    "accents",
    "countryOfOrigin",
    "sleeveType",
    "personalizationInstructions",
})
# Tag-evidence fields: blank stays a warning (never invent), not DNA.
EBAY_OPTIONAL_EVIDENCE_KEYS = frozenset({"material", "fabricType", "garmentCare"})
DNA_VALUE = "Does Not Apply"
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
    "fabric weight",
    "theme",
    "performance activity",
    "accents",
    "country of origin",
    "sleeve type",
    "personalization instructions",
})

# Mirrors vendoo-studio/src/marketplaceFields.ts ETSY_CATEGORY_OPTIONALS (+ fabricPattern alias).
ETSY_CATEGORY_OPTIONAL_KEYS = (
    "clothingStyle",
    "sleeveLength",
    "neckline",
    "closure",
    "graphic",
    "collarStyle",
    "holiday",
    "occasion",
    "pattern",
    "fabricPattern",
    "sustainability",
)
ETSY_OPTIONAL_ALWAYS_DEFAULTS = {
    "clothingStyle": "Minimalist",
    "neckline": "Crew",
    "closure": "Pullover",
    "pattern": "Solid",
    "fabricPattern": "Solid",
}
# Event/theme attributes — DNA unless the item literally matches.
ETSY_OPTIONAL_DNA_KEYS = frozenset({
    "graphic",
    "collarStyle",
    "holiday",
    "occasion",
    "sustainability",
})
ETSY_OPTIONAL_MUST_FILL_LOOKUPS = frozenset({
    "clothing style",
    "sleeve length",
    "neckline",
    "closure",
    "graphic",
    "collar style",
    "holiday",
    "occasion",
    "pattern",
    "fabric pattern",
    "sustainability",
})
ETSY_OPTIONAL_DNA_LOOKUPS = frozenset({
    "graphic",
    "collar style",
    "holiday",
    "occasion",
    "sustainability",
})

# Mirrors vendoo-studio/src/marketplaceFields.ts DEPOP_CATEGORY_OPTIONALS.
DEPOP_CATEGORY_OPTIONAL_KEYS = (
    "source",
    "age",
    "style",
    "occasion",
    "parcelSize",
    "sizeGrouping",
    "material",
)
DEPOP_OPTIONAL_DNA_KEYS = frozenset({
    "sizeGrouping",  # Regular sizing — omit / Does Not Apply
})
DEPOP_OPTIONAL_EVIDENCE_KEYS = frozenset({"material"})
DEPOP_OPTIONAL_MUST_FILL_LOOKUPS = frozenset({
    "source",
    "age",
    "style",
    "occasion",
    "parcel size",
    "size grouping",
    "material",
})
DEPOP_OPTIONAL_DNA_LOOKUPS = frozenset({
    "size grouping",
})
DEPOP_DEFAULT_STYLES = ("Casual", "Retro", "Boho")
DEPOP_DEFAULT_OCCASIONS = ("Casual", "Going out", "Vacation")

VALID_ETSY_WHO = frozenset({
    "Another company or person",
    "A member of my shop",
    "I did",
})
VALID_ETSY_WHAT = frozenset({
    "A finished product",
    "A supply or tool to make things",
})
VALID_DEPOP_GROUPING = frozenset({"Maternity", "Petite", "Plus size", "Tall"})
VALID_DEPOP_PARCEL = (
    "Extra extra small",
    "Extra small",
    "Small",
    "Medium",
    "Large",
    "Extra large",
)
MODERN_ETSY_WHEN = (
    "made to order",
    "not yet made",
    "2020",
    "2010 - 2019",
    "2007 - 2009",
    "recently",
)
ETSY_WHEN_ALIASES = (
    ("made to order", "Made To Order (Not Yet Made)"),
    ("not yet made", "Made To Order (Not Yet Made)"),
    ("2020 - 2026", "2020 - 2026 (Recently)"),
    ("2020s", "2020 - 2026 (Recently)"),
    ("2010 - 2019", "2010 - 2019 (Recently)"),
    ("2010s", "2010 - 2019 (Recently)"),
    ("2007 - 2009", "2007 - 2009 (Recently)"),
    ("2000 - 2006", "2000 - 2006 (Vintage)"),
    ("2000s", "2000 - 2006 (Vintage)"),
    ("before 2007", "Before 2007 (Vintage)"),
    ("1990s", "1990s (Vintage)"),
    ("1980s", "1980s (Vintage)"),
    ("1970s", "1970s (Vintage)"),
    ("1960s", "1960s (Vintage)"),
    ("1950s", "1950s (Vintage)"),
    ("1940s", "1940s (Vintage)"),
    ("1930s", "1930s (Vintage)"),
    ("1920s", "1920s (Vintage)"),
    ("1910s", "1910s (Vintage)"),
    ("1900 - 1909", "1900 - 1909 (Vintage)"),
    ("1800s", "1800s (Vintage)"),
    ("1700s", "1700s (Vintage)"),
    ("before 1700", "Before 1700 (Vintage)"),
    ("vintage", "Before 2007 (Vintage)"),
)
DEFAULT_ETSY_WHEN = "2010 - 2019 (Recently)"
UNKNOWN_ETSY_WHEN = frozenset({
    "unknown", "does not apply", "n/a", "na", "n.a.", "not sure", "not shown",
    "select", "----", "-", "d", "none", "modern",
})
TITLE_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "with", "for", "in", "on", "to",
})
PHYSICAL_DESCRIPTION_MARKERS = ("size:", "condition:", "measurements:")


class ValidationResult(BaseModel):
    valid: bool
    errors: list[dict[str, str]] = Field(default_factory=list)
    warnings: list[dict[str, str]] = Field(default_factory=list)
    info: list[dict[str, str]] = Field(default_factory=list)

    @property
    def can_send(self) -> bool:
        return self.valid and not self.errors


def _add(result: ValidationResult, field: str, message: str, *, warning: bool = False) -> None:
    item = {"field": field, "message": message}
    bucket = result.warnings if warning else result.errors
    if any(existing["field"] == field and existing["message"] == message for existing in bucket):
        return
    if not warning and any(existing["field"] == field and existing["message"] == message for existing in result.errors):
        return
    bucket.append(item)
    if not warning:
        result.valid = False


def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    text = str(value).strip()
    return [text] if text else []


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _mapping(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


@lru_cache(maxsize=1)
def _dropdowns() -> dict[str, Any]:
    path = skills_dir() / "list-this" / "references" / "vendoo-dropdown-options.json"
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _etsy_when_options() -> list[str]:
    forms = (_dropdowns().get("forms") or {}).get("etsy") or {}
    values = forms.get("whenMade") or []
    return [str(item) for item in values if str(item).strip()]


def _dedupe_schema_errors(errors: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for err in errors:
        field = err.get("field") or ""
        message = err.get("message") or ""
        key = (field, message)
        if key in seen:
            continue
        seen.add(key)
        out.append({"field": field, "message": message})
    return out


def _title_tokens(title: str) -> list[str]:
    return [part for part in re.split(r"\s+", title.strip()) if part]


def _title_follows_formula(title: str, brand: str, size: str) -> bool:
    tokens = [token.lower() for token in _title_tokens(title)]
    if len(tokens) < 4:
        return False
    if brand:
        brand_tokens = [part.lower() for part in brand.split() if part]
        if tokens[:len(brand_tokens)] != brand_tokens:
            return False
        rest = tokens[len(brand_tokens):]
    else:
        rest = tokens
    if size and rest:
        size_token = size.lower()
        if rest[0] != size_token and size_token not in rest[:2]:
            return False
    meaningful = [token for token in tokens if token not in TITLE_STOPWORDS]
    return len(meaningful) >= 4


def _description_follows_formula(description: str) -> bool:
    text = description.strip()
    if len(text) < 80 or "\n" not in text:
        return False
    lower = text.lower()
    return all(marker in lower for marker in PHYSICAL_DESCRIPTION_MARKERS)


def _category_is_terminal(path: str) -> bool:
    parts = [part.strip() for part in re.split(r"\s*>\s*", path) if part.strip()]
    return len(parts) >= 4


def _department_matches_category(department: str, category_path: str) -> bool:
    dep = department.lower()
    path = category_path.lower()
    if not dep or not path:
        return True
    if "women" in dep and "men" in path and "women" not in path:
        return False
    if dep == "men" and "women" in path:
        return False
    return True


def _collapse_option(text: str) -> str:
    collapsed = re.sub(r"[\s\-–—/:]+", " ", str(text or "").strip().lower())
    return collapsed.strip()


def _option_key(text: str) -> str:
    return _collapse_option(str(text or "").split("(", 1)[0])


def _canonical_option(value: str, allowed: Iterable[str]) -> str | None:
    needle = str(value or "").strip()
    if not needle:
        return None
    needle_full = _collapse_option(needle)
    needle_key = _option_key(needle)
    ranked = sorted(
        (
            str(option).strip()
            for option in allowed
            if str(option).strip() and str(option).strip() != "----"
        ),
        key=lambda option: len(_option_key(option)),
        reverse=True,
    )
    for option in ranked:
        option_full = _collapse_option(option)
        option_key = _option_key(option)
        if needle_full == option_full or needle_key == option_key:
            return option
        if option_key and (
            needle_key.startswith(f"{option_key} ")
            or needle_full.startswith(f"{option_key} ")
            or needle_full.startswith(f"{option_full} ")
        ):
            return option
    return None


def _allowed_match(value: str, allowed: Iterable[str]) -> bool:
    return _canonical_option(value, allowed) is not None


def _normalize_when_text(text: str) -> str:
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(text or ""))
    spaced = re.sub(r"[–—]", "-", spaced)
    spaced = re.sub(r"[_-]+", " ", spaced)
    return re.sub(r"\s+", " ", spaced).strip().lower()


def _canonical_etsy_when(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    normalized = _normalize_when_text(raw)
    if normalized in UNKNOWN_ETSY_WHEN:
        return DEFAULT_ETSY_WHEN
    for needle, mapped in ETSY_WHEN_ALIASES:
        if _normalize_when_text(needle) in normalized:
            return mapped
    year_match = re.search(r"\b(17\d{2}|18\d{2}|19\d{2}|20\d{2})\b", normalized)
    if not year_match:
        return raw
    year = int(year_match.group(1))
    if year >= 2020:
        return "2020 - 2026 (Recently)"
    if year >= 2010:
        return "2010 - 2019 (Recently)"
    if year >= 2007:
        return "2007 - 2009 (Recently)"
    if year >= 2000:
        return "2000 - 2006 (Vintage)"
    if year >= 1990:
        return "1990s (Vintage)"
    if year >= 1980:
        return "1980s (Vintage)"
    if year >= 1970:
        return "1970s (Vintage)"
    if year >= 1960:
        return "1960s (Vintage)"
    if year >= 1950:
        return "1950s (Vintage)"
    if year >= 1940:
        return "1940s (Vintage)"
    if year >= 1930:
        return "1930s (Vintage)"
    if year >= 1920:
        return "1920s (Vintage)"
    if year >= 1910:
        return "1910s (Vintage)"
    if year >= 1900:
        return "1900 - 1909 (Vintage)"
    if year >= 1800:
        return "1800s (Vintage)"
    if year >= 1700:
        return "1700s (Vintage)"
    return "Before 1700 (Vintage)"


def _etsy_when_raw(etsy: dict[str, Any], listing: dict[str, Any] | None = None) -> str:
    for key in (
        "when_made", "whenMade", "when made", "whenWasItMade", "whenWasItMade?",
        "When Was It Made?", "When Made",
    ):
        text = _scalar_text(etsy.get(key)) if key in etsy else None
        if text:
            return text
    ebay = (listing or {}).get("ebay_specifics")
    if isinstance(ebay, dict):
        text = _scalar_text(ebay.get("yearManufactured") or ebay.get("year_manufactured"))
        if text:
            return text
    return ""


def _etsy_who_raw(etsy: dict[str, Any]) -> str:
    for key in ("who_made", "whoMade", "whoMadeIt", "whoMadeIt?", "Who Made It?"):
        text = _scalar_text(etsy.get(key)) if key in etsy else None
        if text:
            return text
    return ""


def _etsy_what_raw(etsy: dict[str, Any]) -> str:
    for key in ("what_is", "whatIs", "whatIsIt", "whatIsIt?", "What Is It?"):
        text = _scalar_text(etsy.get(key)) if key in etsy else None
        if text:
            return text
    return ""


def _resolve_etsy_when(raw: str, options: list[str]) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    mapped = _canonical_etsy_when(text)
    allowed = options or [mapped, DEFAULT_ETSY_WHEN]
    for candidate in (mapped, text):
        hit = _canonical_option(candidate, allowed)
        if hit:
            return hit
    if options:
        mapped_key = _option_key(mapped or text)
        for option in sorted(options, key=lambda item: len(_option_key(item)), reverse=True):
            option_key = _option_key(option)
            if option_key and len(option_key) >= 4 and (
                option_key in mapped_key or mapped_key in option_key
            ):
                return option
        for option in options:
            if "2010" in option:
                return option
        return options[0]
    return mapped or DEFAULT_ETSY_WHEN


def _etsy_when_is_vintage_or_handmade(when_made: str, who_made: str, what_is: str) -> bool:
    when = when_made.lower()
    who = who_made.lower()
    what = what_is.lower()
    if "vintage" in when or "before 2007" in when or "1990" in when or "1980" in when:
        return True
    if "i did" in who or "member of my shop" in who:
        return True
    if "supply or tool" in what:
        return True
    if "digital" in what:
        return True
    return False


def _etsy_listing_type(etsy: dict[str, Any] | None) -> str:
    specs = etsy or {}
    return _text(specs.get("listing_type") or specs.get("listingType"))


def _is_etsy_digital_listing(payload: dict[str, Any]) -> bool:
    etsy = _mapping(payload.get("etsy_specifics")) or {}
    listing_type = _etsy_listing_type(etsy).lower()
    if "digital" in listing_type:
        return True
    what = _text(etsy.get("what_is") or etsy.get("whatIsIt")).lower()
    return "digital" in what


def _etsy_when_is_modern(when_made: str) -> bool:
    when = when_made.lower()
    if not when:
        return True
    return any(token in when for token in MODERN_ETSY_WHEN)


def _evidence_unknown(description: str, *needles: str) -> bool:
    lower = description.lower()
    return any(needle in lower for needle in needles)


def _ebay_season_parts(value: Any) -> list[str]:
    """Split Season chips / comma lists into individual tokens."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        parts: list[str] = []
        for item in value:
            parts.extend(_ebay_season_parts(item))
        return parts
    text = _text(value)
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


def _exact_ebay_season(part: str) -> str | None:
    needle = _collapse_option(part)
    key = _option_key(part)
    for option in VALID_EBAY_SEASONS:
        if needle == _collapse_option(option) or key == _option_key(option):
            return option
    return None


def _ebay_season_haystack(listing: dict | None, ebay: dict | None = None) -> str:
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
    hay = _ebay_season_haystack(listing, ebay)
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
        canon = _exact_ebay_season(str(season)) or (
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


def _normalize_ebay_season_value(
    value: Any,
    *,
    listing: dict | None = None,
    ebay: dict | None = None,
) -> tuple[Any, bool]:
    """Force Season to real calendar chips; infer one when DNA / blank / all-year."""
    inferred = infer_ebay_season(listing, ebay=ebay)
    parts = _ebay_season_parts(value)
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
        canon = _exact_ebay_season(part)
        if canon:
            if canon not in kept:
                kept.append(canon)
            if part != canon:
                changed = True
            continue
        # Leave unrecognized tokens so validate_listing can still surface them.
        if part not in kept:
            kept.append(part)

    valid = [part for part in kept if _exact_ebay_season(part)]
    invalid = [part for part in kept if _exact_ebay_season(part) is None]
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


def _ebay_optional_raw(ebay: dict, key: str) -> Any:
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
    return None


def _ebay_optional_blank(value: Any) -> bool:
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
    hay = _ebay_season_haystack(listing, ebay)
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


def _infer_ebay_fabric_type(listing: dict | None, ebay: dict | None) -> str | None:
    ebay = ebay if isinstance(ebay, dict) else {}
    material = _text(_ebay_optional_raw(ebay, "material") or (listing or {}).get("material"))
    if material:
        first = material.split(",")[0].strip()
        if first:
            return first
    hay = _ebay_season_haystack(listing, ebay)
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
        if _ebay_optional_blank(_ebay_optional_raw(ebay, key)):
            ebay[key] = value
            nested = ebay.get("category_specifics")
            if isinstance(nested, dict) and key in nested and _ebay_optional_blank(nested.get(key)):
                nested = dict(nested)
                nested[key] = value
                ebay["category_specifics"] = nested
            changed = True

    for key, default in EBAY_OPTIONAL_ALWAYS_DEFAULTS.items():
        set_key(key, default)

    care_unknown = _evidence_unknown(
        _text((listing or {}).get("description")),
        "care tag is not shown",
        "garment care",
        "unverified",
    ) or any(
        token in _text((listing or {}).get("description")).casefold()
        for token in ("garment care is unknown", "care is unknown", "care tag is not shown")
    )
    if not care_unknown and _ebay_optional_blank(_ebay_optional_raw(ebay, "garmentCare")):
        set_key("garmentCare", "Machine Washable")

    if _ebay_optional_blank(_ebay_optional_raw(ebay, "season")) and _ebay_optional_blank(
        _ebay_optional_raw(ebay, "Season")
    ):
        set_key("season", infer_ebay_season(listing, ebay=ebay))
    else:
        normalized, season_changed = _normalize_ebay_season_value(
            _ebay_optional_raw(ebay, "season") or _ebay_optional_raw(ebay, "Season"),
            listing=listing,
            ebay=ebay,
        )
        if season_changed or "Season" in ebay:
            ebay["season"] = normalized
            ebay.pop("Season", None)
            changed = True

    if _ebay_optional_blank(_ebay_optional_raw(ebay, "sleeveLength")):
        set_key("sleeveLength", _infer_ebay_sleeve_length(listing, ebay))

    fabric = _infer_ebay_fabric_type(listing, ebay)
    if fabric and _ebay_optional_blank(_ebay_optional_raw(ebay, "fabricType")):
        set_key("fabricType", fabric)

    vintage_hay = _ebay_season_haystack(listing, ebay)
    if re.search(r"\b(?:vintage|y2k|90s|80s|70s)\b", vintage_hay):
        current_vintage = _text(_ebay_optional_raw(ebay, "vintage"))
        if current_vintage.casefold() == "no" or _ebay_optional_blank(_ebay_optional_raw(ebay, "vintage")):
            ebay["vintage"] = "Yes"
            changed = True

    for key in EBAY_OPTIONAL_DNA_KEYS:
        if key == "personalizationInstructions":
            personalize = _text(_ebay_optional_raw(ebay, "personalize") or "No")
            if personalize.casefold() == "yes":
                continue
        if _ebay_optional_blank(_ebay_optional_raw(ebay, key)):
            set_key(key, DNA_VALUE)

    # Material: copy fabricType fiber when material empty and fabric looks like a fiber.
    if _ebay_optional_blank(_ebay_optional_raw(ebay, "material")):
        fabric_val = _text(_ebay_optional_raw(ebay, "fabricType"))
        if fabric_val and fabric_val.casefold() not in {
            "knit", "jersey", "woven", "canvas", "twill", "microfiber",
        }:
            set_key("material", fabric_val)

    if changed:
        listing["ebay_specifics"] = ebay
    return changed


def _infer_etsy_sleeve_length(listing: dict | None, etsy: dict | None, ebay: dict | None = None) -> str:
    hay = _ebay_season_haystack(listing, ebay if isinstance(ebay, dict) else None)
    if isinstance(etsy, dict):
        hay = f"{hay} {_text(etsy.get('type'))} {_text(etsy.get('sleeveLength'))}".casefold()
    if re.search(r"\b(?:sleeveless|tank|cami|halter|strapless)\b", hay):
        return "Sleeveless"
    if re.search(r"\b(?:3[\s/]*4|three[\s-]*quarter)\s*sleeve\b", hay):
        return "3/4 sleeve"
    if re.search(r"\b(?:long[\s-]*sleeve|ls)\b", hay) or re.search(
        r"\b(?:sweater|hoodie|coat|parka|cardigan|fleece)\b", hay
    ):
        return "Long sleeve"
    if re.search(r"\bhalf[\s-]*sleeve\b", hay):
        return "Half sleeve"
    return "Short sleeve"


def _etsy_neckline_from_ebay(value: str) -> str:
    folded = value.casefold()
    if "v" in folded and "neck" in folded:
        return "V-neck"
    if "henley" in folded:
        return "Henley"
    return "Crew"


def ensure_etsy_category_optionals(listing: dict) -> bool:
    """Fill Etsy Show-Optional-Fields rows: defaults, DNA only when N/A, infer sleeve/pattern."""
    if not isinstance(listing, dict):
        return False
    raw = listing.get("etsy_specifics")
    if not isinstance(raw, dict):
        return False
    etsy = dict(raw)
    ebay = listing.get("ebay_specifics") if isinstance(listing.get("ebay_specifics"), dict) else {}
    changed = False

    def set_key(key: str, value: Any) -> None:
        nonlocal etsy, changed
        if _ebay_optional_blank(_ebay_optional_raw(etsy, key)):
            etsy[key] = value
            nested = etsy.get("category_specifics")
            if isinstance(nested, dict) and key in nested and _ebay_optional_blank(nested.get(key)):
                nested = dict(nested)
                nested[key] = value
                etsy["category_specifics"] = nested
            changed = True

    # Prefer eBay apparel specifics when Etsy rows are still empty.
    ebay_map = {
        "closure": _text(_ebay_optional_raw(ebay, "closure")),
        "collarStyle": _text(_ebay_optional_raw(ebay, "collarStyle")),
        "sleeveLength": _text(_ebay_optional_raw(ebay, "sleeveLength")),
        "neckline": _text(_ebay_optional_raw(ebay, "neckline")),
        "pattern": _text(_ebay_optional_raw(ebay, "pattern")),
    }
    if ebay_map["sleeveLength"]:
        folded = ebay_map["sleeveLength"].casefold()
        if "sleeveless" in folded:
            ebay_map["sleeveLength"] = "Sleeveless"
        elif "3/4" in folded or "three" in folded:
            ebay_map["sleeveLength"] = "3/4 sleeve"
        elif "long" in folded:
            ebay_map["sleeveLength"] = "Long sleeve"
        elif "half" in folded:
            ebay_map["sleeveLength"] = "Half sleeve"
        else:
            ebay_map["sleeveLength"] = "Short sleeve"
    if ebay_map["neckline"]:
        ebay_map["neckline"] = _etsy_neckline_from_ebay(ebay_map["neckline"])
    if ebay_map["pattern"]:
        # Etsy fabric pattern chips use sentence case matching dropdown JSON.
        pattern = ebay_map["pattern"]
        for option in (
            "Camouflage", "Check", "Floral", "Geometric", "Plaid", "Polka dot",
            "Solid", "Striped", "Tie dye", "Ombré",
        ):
            if pattern.casefold() == option.casefold():
                ebay_map["pattern"] = option
                break

    for key, default in ETSY_OPTIONAL_ALWAYS_DEFAULTS.items():
        source = ebay_map.get(key) if key in {"closure", "neckline", "pattern"} else ""
        set_key(key, source or default)

    if _ebay_optional_blank(_ebay_optional_raw(etsy, "fabricPattern")):
        pattern = _text(_ebay_optional_raw(etsy, "pattern") or ebay_map.get("pattern") or "Solid")
        set_key("fabricPattern", pattern)
    if _ebay_optional_blank(_ebay_optional_raw(etsy, "pattern")):
        set_key("pattern", _text(_ebay_optional_raw(etsy, "fabricPattern") or "Solid"))

    if _ebay_optional_blank(_ebay_optional_raw(etsy, "sleeveLength")):
        set_key(
            "sleeveLength",
            ebay_map.get("sleeveLength") or _infer_etsy_sleeve_length(listing, etsy, ebay),
        )

    hay = _ebay_season_haystack(listing, ebay)
    if re.search(r"\b(?:streetwear|graphic\s*tee|skate|hip[\s-]*hop)\b", hay):
        if _text(_ebay_optional_raw(etsy, "clothingStyle")).casefold() == "minimalist":
            etsy["clothingStyle"] = "Streetwear"
            changed = True

    for key in ETSY_OPTIONAL_DNA_KEYS:
        if key == "graphic":
            if re.search(r"\b(?:graphic|logo|print|slogan|saying|brand\s*logo)\b", hay):
                if _ebay_optional_blank(_ebay_optional_raw(etsy, "graphic")):
                    # Prefer a concrete Etsy chip when the tee is clearly branded/graphic.
                    set_key("graphic", "Brand & logo")
                continue
        if key == "sustainability":
            if re.search(r"\b(?:organic|hemp|linen|recycled)\b", hay):
                if re.search(r"\borganic\b", hay):
                    set_key("sustainability", "Organic cotton")
                elif re.search(r"\bhemp\b", hay):
                    set_key("sustainability", "Hemp")
                elif re.search(r"\blinen\b", hay):
                    set_key("sustainability", "Linen")
                elif re.search(r"\brecycled\b", hay):
                    set_key("sustainability", "Recycled polyester")
                continue
        if key == "holiday" and re.search(
            r"\b(?:christmas|halloween|thanksgiving|valentine|hanukkah|easter|st\.?\s*patrick)\b",
            hay,
        ):
            continue
        if key == "occasion" and re.search(
            r"\b(?:wedding|birthday|graduation|engagement|pride|bachelor|baby\s*shower)\b",
            hay,
        ):
            continue
        if _ebay_optional_blank(_ebay_optional_raw(etsy, key)):
            set_key(key, DNA_VALUE)

    if changed:
        listing["etsy_specifics"] = etsy
    return changed


def _infer_depop_parcel_size(listing: dict) -> str:
    """Depop's parcel tier is priced by weight — empty when the listing has no weight."""
    try:
        lb = float(listing.get("weight_lb") or 0)
        oz = float(listing.get("weight_oz") or 0)
    except (TypeError, ValueError):
        lb, oz = 0.0, 0.0
    total_oz = max(0.0, lb * 16 + oz)
    if total_oz <= 0:
        return ""
    if total_oz < 4:
        return "Extra extra small"
    if total_oz < 8:
        return "Extra small"
    if total_oz < 12:
        return "Small"
    if total_oz < 16:
        return "Medium"
    if total_oz < 32:
        return "Large"
    return "Extra large"


def _pad_depop_tags(values: list[str], defaults: tuple[str, ...], *, limit: int = 3) -> list[str]:
    kept: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in kept:
            kept.append(text)
        if len(kept) >= limit:
            return kept[:limit]
    for default in defaults:
        if default not in kept:
            kept.append(default)
        if len(kept) >= limit:
            break
    return kept[:limit]


def _map_depop_material(value: str) -> str | None:
    raw = _text(value)
    if not raw:
        return None
    folded = raw.casefold()
    aliases = {
        "spandex": "Elastane / Lycra / Spandex",
        "lycra": "Elastane / Lycra / Spandex",
        "elastane": "Elastane / Lycra / Spandex",
        "vegan leather": "Faux leather",
        "faux leather": "Faux leather",
        "genuine leather": "Leather",
        "real leather": "Leather",
        "faux fur": "Faux fur",
        "organic cotton": "Cotton - Organic",
        "recycled cotton": "Cotton - Recycled",
        "recycled polyester": "Polyester - Recycled",
    }
    for needle, mapped in aliases.items():
        if needle in folded:
            return mapped
    hit = _canonical_option(raw, VALID_DEPOP_MATERIAL)
    if hit:
        return hit
    cleaned = re.sub(r"\b(?:blend|pure|100%)\b", "", raw, flags=re.I).strip(" ,")
    return _canonical_option(cleaned, VALID_DEPOP_MATERIAL) if cleaned else None


def ensure_depop_category_optionals(listing: dict) -> bool:
    """Fill Depop Show-Optional-Fields rows; omit size grouping for Regular."""
    if not isinstance(listing, dict):
        return False
    raw = listing.get("depop_specifics")
    if not isinstance(raw, dict):
        return False
    depop = dict(raw)
    ebay = listing.get("ebay_specifics") if isinstance(listing.get("ebay_specifics"), dict) else {}
    changed = False
    hay = _ebay_season_haystack(listing, ebay)

    def set_key(key: str, value: Any) -> None:
        nonlocal depop, changed
        current = depop.get(key)
        if key in {"style", "occasion", "material"}:
            if _as_list(current):
                return
        elif not _ebay_optional_blank(current):
            return
        depop[key] = value
        changed = True

    if _ebay_optional_blank(depop.get("source")):
        source = "Vintage" if re.search(r"\b(?:vintage|deadstock|y2k|90s|80s|70s)\b", hay) else "Preloved"
        set_key("source", source)

    if _ebay_optional_blank(depop.get("age")):
        age = "Modern"
        for decade in ("50s", "60s", "70s", "80s", "90s"):
            if re.search(rf"\b{decade}\b", hay):
                age = decade
                break
        if age == "Modern" and re.search(r"\by2k\b", hay):
            age = "y2k"
        set_key("age", age)

    styles = _as_list(depop.get("style"))
    style_hits = [_canonical_option(style, VALID_DEPOP_STYLE) for style in styles]
    if not styles:
        set_key("style", list(DEPOP_DEFAULT_STYLES))
    elif all(style_hits) and len({hit for hit in style_hits if hit}) < 3:
        mapped = []
        for hit in style_hits:
            if hit and hit not in mapped:
                mapped.append(hit)
        if re.search(r"\b(?:streetwear|graphic|skate)\b", hay) and "Streetwear" not in mapped:
            mapped.insert(0, "Streetwear")
        if re.search(r"\b(?:boho|floral|peasant)\b", hay) and "Boho" not in mapped:
            mapped.append("Boho")
        padded = _pad_depop_tags(mapped, DEPOP_DEFAULT_STYLES, limit=3)
        if padded != styles:
            depop["style"] = padded
            changed = True

    occasions = _as_list(depop.get("occasion"))
    occasion_hits = [_canonical_option(occasion, VALID_DEPOP_OCCASION) for occasion in occasions]
    if not occasions:
        mapped = []
        ebay_occ = ebay.get("occasion") if isinstance(ebay, dict) else None
        for occasion in _as_list(ebay_occ):
            folded = str(occasion or "").casefold()
            alias = {
                "workwear": "Work",
                "activewear": "Workout",
                "formal": "Special Occasion",
                "party/cocktail": "Party",
                "everyday": "Casual",
                "travel": "Vacation",
                "business": "Work",
                "casual": "Casual",
            }
            mapped_value = None
            for key, value in alias.items():
                if key in folded:
                    mapped_value = value
                    break
            hit = mapped_value or _canonical_option(str(occasion), VALID_DEPOP_OCCASION)
            if hit and hit not in mapped:
                mapped.append(hit)
        season = _text(ebay.get("season") if isinstance(ebay, dict) else "") or infer_ebay_season(listing, ebay=ebay)
        if season == "Summer" and "Summer" not in mapped:
            mapped.append("Summer")
        if season == "Winter" and "Winter" not in mapped:
            mapped.append("Winter")
        set_key("occasion", _pad_depop_tags(mapped, DEPOP_DEFAULT_OCCASIONS, limit=3))
    elif all(occasion_hits) and len({hit for hit in occasion_hits if hit}) < 3:
        mapped = []
        for hit in occasion_hits:
            if hit and hit not in mapped:
                mapped.append(hit)
        padded = _pad_depop_tags(mapped, DEPOP_DEFAULT_OCCASIONS, limit=3)
        if padded != occasions:
            depop["occasion"] = padded
            changed = True

    # Depop prices the parcel by weight, so the weight on the listing wins over any
    # tier the model picked on its own.
    parcel = _text(depop.get("parcelSize") or depop.get("parcel_size"))
    from_weight = _infer_depop_parcel_size(listing)
    if from_weight:
        if parcel != from_weight or "parcel_size" in depop:
            depop["parcelSize"] = from_weight
            depop.pop("parcel_size", None)
            changed = True
    elif not parcel:
        set_key("parcelSize", "Medium")
        depop.pop("parcel_size", None)

    size_type = _text(listing.get("sizeType") or ebay.get("sizeType")).casefold()
    grouping = _text(depop.get("sizeGrouping") or depop.get("size_grouping"))
    wanted = {
        "petite": "Petite",
        "plus": "Plus size",
        "plus size": "Plus size",
        "tall": "Tall",
        "maternity": "Maternity",
    }.get(size_type)
    if wanted and grouping != wanted:
        depop["sizeGrouping"] = wanted
        depop.pop("size_grouping", None)
        changed = True

    if not _as_list(depop.get("material")):
        candidates = [
            *_as_list(depop.get("material")),
            *_as_list(ebay.get("material") if isinstance(ebay, dict) else None),
            *_as_list(ebay.get("fabricType") if isinstance(ebay, dict) else None),
        ]
        mapped_materials: list[str] = []
        for candidate in candidates:
            hit = _map_depop_material(str(candidate))
            if hit and hit not in mapped_materials:
                mapped_materials.append(hit)
        if mapped_materials:
            depop["material"] = mapped_materials[:4]
            changed = True

    if changed:
        listing["depop_specifics"] = depop
    return changed


def ensure_poshmark_style_tags(listing: dict) -> bool:
    """Fill Poshmark style tags when empty so Additional Details is not blank."""
    if not isinstance(listing, dict):
        return False
    raw = listing.get("poshmark_specifics")
    if not isinstance(raw, dict):
        return False
    tags = _as_list(raw.get("styleTags") or raw.get("style_tags"))
    if tags:
        return False
    depop = listing.get("depop_specifics") if isinstance(listing.get("depop_specifics"), dict) else {}
    ebay = listing.get("ebay_specifics") if isinstance(listing.get("ebay_specifics"), dict) else {}
    candidates = [
        *_as_list(depop.get("style")),
        _text(ebay.get("style")),
        _text(ebay.get("features")),
        "Casual",
    ]
    filled: list[str] = []
    for candidate in candidates:
        text = _text(candidate)
        if text and text not in filled and text.casefold() != DNA_VALUE.casefold():
            filled.append(text)
        if len(filled) >= 3:
            break
    while len(filled) < 3:
        for fallback in ("Casual", "Retro", "Vintage"):
            if fallback not in filled:
                filled.append(fallback)
            if len(filled) >= 3:
                break
    posh = dict(raw)
    posh["styleTags"] = filled[:3]
    listing["poshmark_specifics"] = posh
    return True


def ensure_mercari_shipping_label(listing: dict) -> bool:
    if not isinstance(listing, dict):
        return False
    raw = listing.get("mercari_specifics")
    if not isinstance(raw, dict):
        return False
    if _text(raw.get("shippingLabel") or raw.get("shipping_label")):
        return False
    mercari = dict(raw)
    mercari["shippingLabel"] = "USPS Ground Advantage"
    listing["mercari_specifics"] = mercari
    return True


# Containers keep their own names — only leaf value keys are canonicalized.
KEY_CANONICAL_SKIP = frozenset({"category_specifics", "marketplace_specifics", "marketplaceSpecifics"})


def _squash_key(text: str) -> str:
    from vendoo_studio.services.fill_log import squash_field_key

    return squash_field_key(text)


@lru_cache(maxsize=1)
def _canonical_by_squash() -> dict[str, str]:
    """Known JSON keys indexed by their case/separator-free form."""
    from vendoo_studio.services.registry import LABEL_TO_JSON_KEY

    known: list[str] = [
        *ListingSchema.model_fields,
        *LABEL_TO_JSON_KEY.values(),
        *REQUIRED_EBAY_KEYS,
        *EBAY_CATEGORY_OPTIONAL_KEYS,
        *ETSY_CATEGORY_OPTIONAL_KEYS,
        *DEPOP_CATEGORY_OPTIONAL_KEYS,
    ]
    return {_squash_key(key): key for key in known if _squash_key(key)}


def _canonicalize_record_keys(record: dict, *, allowed: frozenset[str] | None = None) -> bool:
    """Rename keys that differ from the canonical JSON key only by case or separators.

    Heals listings where a gap fill wrote `sizetype` instead of `sizeType`, which reads
    as an empty required field even though the value is sitting in the JSON.
    """
    from vendoo_studio.services.fill_log import field_lookup_key
    from vendoo_studio.services.registry import label_to_json_key

    changed = False
    for key in list(record):
        if key in KEY_CANONICAL_SKIP:
            continue
        value = record[key]
        if isinstance(value, dict):
            continue
        squashed = _squash_key(key)
        known = _canonical_by_squash()
        # Keys the app reads may be reached through label normalization; anything else
        # is only renamed when it differs from its JSON key by case or separators alone.
        canonical = known.get(squashed) or known.get(_squash_key(field_lookup_key(key)))
        if not canonical:
            canonical = label_to_json_key(field_lookup_key(key))
            if not canonical or _squash_key(canonical) != squashed:
                continue
        if canonical == key:
            continue
        if allowed is not None and canonical not in allowed:
            continue
        # Same field under two spellings: the canonical value is the one everything reads.
        if _ebay_optional_blank(record.get(canonical)):
            record[canonical] = value
        record.pop(key, None)
        changed = True
    return changed


def canonicalize_listing_keys(listing: dict) -> bool:
    if not isinstance(listing, dict):
        return False
    changed = _canonicalize_record_keys(listing, allowed=frozenset(ListingSchema.model_fields))
    for marketplace in FILLABLE_MARKETPLACES:
        specifics = listing.get(f"{marketplace}_specifics")
        if not isinstance(specifics, dict):
            continue
        if _canonicalize_record_keys(specifics):
            changed = True
        nested = specifics.get("category_specifics")
        if isinstance(nested, dict) and _canonicalize_record_keys(nested):
            changed = True
    if _promote_required_ebay_specifics(listing):
        changed = True
    return changed


def _promote_required_ebay_specifics(listing: dict) -> bool:
    """Lift required eBay keys out of category_specifics — the filler reads them flat."""
    ebay = listing.get("ebay_specifics")
    if not isinstance(ebay, dict):
        return False
    nested = ebay.get("category_specifics")
    if not isinstance(nested, dict):
        return False
    changed = False
    for key in REQUIRED_EBAY_KEYS:
        if not _ebay_optional_blank(ebay.get(key)):
            continue
        value = nested.get(key)
        if _ebay_optional_blank(value):
            continue
        ebay[key] = value
        changed = True
    return changed


def normalize_listing_dropdowns(listing: dict) -> bool:
    """Rewrite stale Depop/Etsy dropdown values to the current Vendoo options."""
    if not isinstance(listing, dict):
        return False
    changed = canonicalize_listing_keys(listing)

    # Shipping weight often lands only under marketplace specifics — promote it.
    if "weight_lb" not in listing and "weight_oz" not in listing:
        ebay = listing.get("ebay_specifics") if isinstance(listing.get("ebay_specifics"), dict) else {}
        pounds = ebay.get("pounds") if isinstance(ebay, dict) else None
        ounces = ebay.get("ounces") if isinstance(ebay, dict) else None
        if pounds is None and ounces is None:
            for key in ("mercari_specifics", "etsy_specifics", "depop_specifics"):
                block = listing.get(key)
                if isinstance(block, dict):
                    if pounds is None and block.get("pounds") is not None:
                        pounds = block.get("pounds")
                    if ounces is None and block.get("ounces") is not None:
                        ounces = block.get("ounces")
        try:
            lb = int(pounds or 0)
            oz = int(ounces or 0)
        except (TypeError, ValueError):
            lb, oz = 0, 0
        if lb > 0 or oz > 0:
            listing["weight_lb"] = lb
            listing["weight_oz"] = oz
            changed = True

    ebay = listing.get("ebay_specifics")
    if isinstance(ebay, dict):
        raw_season = ebay.get("season")
        if raw_season in (None, "") and ebay.get("Season") not in (None, ""):
            raw_season = ebay.get("Season")
        missing = raw_season in (None, "", [], ()) and "season" not in ebay and "Season" not in ebay
        if missing:
            ebay = dict(ebay)
            ebay["season"] = infer_ebay_season(listing, ebay=ebay)
            ebay.pop("Season", None)
            listing["ebay_specifics"] = ebay
            changed = True
        else:
            normalized_season, season_changed = _normalize_ebay_season_value(
                raw_season,
                listing=listing,
                ebay=ebay,
            )
            if season_changed or ("Season" in ebay and ebay.get("Season") != normalized_season):
                ebay = dict(ebay)
                ebay["season"] = (
                    infer_ebay_season(listing, ebay=ebay)
                    if normalized_season is None
                    else normalized_season
                )
                ebay.pop("Season", None)
                listing["ebay_specifics"] = ebay
                changed = True

    if ensure_ebay_category_optionals(listing):
        changed = True
    if ensure_etsy_category_optionals(listing):
        changed = True
    if ensure_depop_category_optionals(listing):
        changed = True
    if ensure_poshmark_style_tags(listing):
        changed = True
    if ensure_mercari_shipping_label(listing):
        changed = True

    depop = listing.get("depop_specifics")
    if isinstance(depop, dict):
        raw = _text(depop.get("parcelSize") or depop.get("parcel_size"))
        canonical = _canonical_option(raw, VALID_DEPOP_PARCEL) if raw else None
        if canonical and canonical != raw:
            depop = dict(depop)
            depop["parcelSize"] = canonical
            if "parcel_size" in depop:
                depop["parcel_size"] = canonical
            listing["depop_specifics"] = depop
            changed = True
        styles = _as_list(depop.get("style"))
        mapped: list[str] = []
        had_invalid = False
        for style in styles:
            hit = _canonical_option(style, VALID_DEPOP_STYLE)
            if hit:
                if hit not in mapped:
                    mapped.append(hit)
            elif str(style or "").strip():
                had_invalid = True
        if styles and had_invalid:
            if not mapped:
                mapped = ["Casual", "Retro", "Boho"]
            mapped = mapped[:3]
            if mapped != styles:
                depop = dict(depop)
                depop["style"] = mapped
                listing["depop_specifics"] = depop
                changed = True

    etsy = listing.get("etsy_specifics")
    if isinstance(etsy, dict):
        etsy = dict(etsy)
        who = _etsy_who_raw(etsy)
        what = _etsy_what_raw(etsy)
        when_raw = _etsy_when_raw(etsy, listing)
        if who and _text(etsy.get("who_made")) != who:
            etsy["who_made"] = who
            changed = True
        if what and _text(etsy.get("what_is")) != what:
            etsy["what_is"] = what
            changed = True
        canonical_when = _resolve_etsy_when(when_raw, _etsy_when_options()) if when_raw else ""
        if canonical_when and _text(etsy.get("when_made")) != canonical_when:
            etsy["when_made"] = canonical_when
            if "whenMade" in etsy:
                etsy["whenMade"] = canonical_when
            changed = True
        listing["etsy_specifics"] = etsy

    return changed


def validate_listing(
    data: dict,
    required_photo_count: Optional[int] = None,
    *,
    require_photos: bool = True,
    selected_marketplaces: list[str] | None = None,
) -> ValidationResult:
    result = ValidationResult(valid=True)
    payload = data if isinstance(data, dict) else {}
    normalize_listing_dropdowns(payload)
    selected = list(selected_marketplaces) if selected_marketplaces is not None else get_selected_marketplaces()
    selected_set = {item.lower() for item in selected}
    digital_listing = _is_etsy_digital_listing(payload)

    schema_errors: list[dict[str, str]] = []
    try:
        ListingSchema.model_validate(payload)
    except ValidationError as exc:
        result.valid = False
        for err in exc.errors():
            field = ".".join(str(loc) for loc in err["loc"])
            message = err["msg"]
            schema_errors.append({
                "field": field,
                "message": f"{field}: {message}" if field else message,
            })

    required_fields = [
        ("title", "Title is required"),
        ("description", "Description is required"),
        ("price", "Price is required"),
        ("brand", "Brand is required"),
        ("sku", "SKU is required"),
    ]
    if not digital_listing:
        required_fields.insert(4, ("size", "Size is required"))
    for field, message in required_fields:
        if field in {err["field"] for err in schema_errors}:
            continue
        value = payload.get(field)
        missing = value is None or (isinstance(value, str) and not value.strip())
        if missing:
            _add(result, field, message)

    for err in _dedupe_schema_errors(schema_errors):
        field = err["field"]
        if field in {"title", "description", "price"} and any(item["field"] == field for item in result.errors):
            continue
        result.errors.append(err)

    title = _text(payload.get("title"))
    description = _text(payload.get("description"))
    brand = _text(payload.get("brand"))
    size = _text(payload.get("size") or payload.get("size_us"))
    if title and len(title) > 80 and not any(err["field"] == "title" for err in result.errors):
        _add(result, "title", "Title must be 80 characters or less")
    if not digital_listing:
        if title and brand and not _title_follows_formula(title, brand, size):
            _add(result, "title", "Title must follow Brand Size Vibe Item Color Fit")
        if description and not _description_follows_formula(description):
            _add(
                result,
                "description",
                "Description must use the physical-item formula, including Size, Condition, and Measurements",
            )
    elif description and "instant download" not in description.lower() and "no physical item" not in description.lower():
        _add(
            result,
            "description",
            "Digital listings must state instant download and that no physical item will be shipped",
            warning=True,
        )

    if not digital_listing:
        if "weight_lb" not in payload and "weight_oz" not in payload:
            _add(result, "weight_oz", "Weight is required")
        else:
            try:
                pounds = int(payload.get("weight_lb") or 0)
                ounces = int(payload.get("weight_oz") or 0)
            except (TypeError, ValueError):
                pounds, ounces = 0, 0
            if pounds <= 0 and ounces <= 0:
                _add(result, "weight_oz", "Weight is required")

        package = _text(payload.get("package_dimensions_in"))
        if package and not re.match(PACKAGE_DIMS_PATTERN, package, re.I):
            _add(result, "package_dimensions_in", "Package dimensions must use LxWxH inches, such as 13x10x3")
        elif not package:
            _add(result, "package_dimensions_in", "Package dimensions are required")
    else:
        package = _text(payload.get("package_dimensions_in"))
        if package and not re.match(PACKAGE_DIMS_PATTERN, package, re.I):
            _add(result, "package_dimensions_in", "Package dimensions must use LxWxH inches, such as 13x10x3")

    category_path = _text(payload.get("category_path"))
    if category_path and not _category_is_terminal(category_path):
        _add(result, "category_path", "Category must be a terminal Vendoo path")
    department = _text(payload.get("department"))
    if department and category_path and not _department_matches_category(department, category_path):
        _add(result, "department", "Department does not match the selected category")

    if require_photos and required_photo_count is not None and required_photo_count == 0:
        _add(result, "photos", "At least one product photo is required")

    ebay = _mapping(payload.get("ebay_specifics"))
    if payload.get("ebay_specifics") is not None and ebay is None:
        _add(result, "ebay_specifics", "eBay specifics must be an object")
        ebay = {}
    ebay = ebay or {}
    if "ebay" in selected_set:
        for key in REQUIRED_EBAY_KEYS:
            if not _text(ebay.get(key)):
                _add(result, f"ebay_specifics.{key}", f"eBay field '{key}' is required")
        for alias, canonical in EBAY_KEY_ALIASES.items():
            if alias in ebay and canonical not in ebay:
                _add(result, f"ebay_specifics.{canonical}", f"eBay key '{alias}' must be '{canonical}'")
        season = ebay.get("season")
        season_parts = _ebay_season_parts(season)
        if not season_parts or any(_exact_ebay_season(part) is None for part in season_parts):
            _add(
                result,
                "ebay_specifics.season",
                "eBay Season must be Spring, Summer, Fall, and/or Winter",
            )
        for key in EBAY_CATEGORY_OPTIONAL_KEYS:
            if key == "season":
                continue
            value = _ebay_optional_raw(ebay, key)
            if _ebay_optional_blank(value):
                if key in EBAY_OPTIONAL_EVIDENCE_KEYS:
                    continue
                _add(
                    result,
                    f"ebay_specifics.{key}",
                    f"eBay optional '{key}' must be filled (or Does Not Apply only when it truly does not apply)",
                )
                continue
            text = _text(value) if not isinstance(value, (list, tuple)) else ",".join(str(v) for v in value)
            is_dna = text.casefold() in {
                DNA_VALUE.casefold(), "n/a", "na", "none", "does not apply",
            }
            if is_dna and key not in EBAY_OPTIONAL_DNA_KEYS:
                _add(
                    result,
                    f"ebay_specifics.{key}",
                    f"eBay '{key}' applies to this item — use a real value, not Does Not Apply",
                )
        ebay_size = _text(ebay.get("size"))
        if size and ebay_size and ebay_size.lower() != size.lower():
            _add(result, "ebay_specifics.size", "eBay size must match the general size")
        care = _text(ebay.get("garmentCare"))
        if care and _evidence_unknown(description, "care tag is not shown", "garment care", "unverified"):
            if "unknown" in description.lower() or "not shown" in description.lower() or "unverified" in description.lower():
                _add(result, "ebay_specifics.garmentCare", "Do not invent garment care when the care tag is not shown")
        material = _text(ebay.get("material") or _ebay_optional_raw(ebay, "material"))
        if material and _evidence_unknown(
            description,
            "material tag is not shown",
            "fiber composition is unknown",
            "material is unknown",
        ):
            _add(result, "ebay_specifics.material", "Do not invent material composition without tag evidence")
        elif not material:
            _add(
                result,
                "ebay_specifics.material",
                "Material evidence is missing. Keep material blank and state the gap in the description.",
                warning=True,
            )

    depop = _mapping(payload.get("depop_specifics"))
    if payload.get("depop_specifics") is not None and depop is None:
        _add(result, "depop_specifics", "Depop specifics must be an object")
        depop = {}
    depop = depop or {}
    if "depop" in selected_set:
        source = _text(depop.get("source"))
        if source and source not in VALID_DEPOP_SOURCE:
            _add(result, "depop_specifics.source", "Depop source is not a current dropdown value")
        elif not source:
            _add(result, "depop_specifics.source", "Depop source is required")
        age = _text(depop.get("age"))
        if age and age not in VALID_DEPOP_AGE:
            _add(result, "depop_specifics.age", "Depop age is not a current dropdown value")
        elif not age:
            _add(result, "depop_specifics.age", "Depop age is required")
        styles = _as_list(depop.get("style"))
        if not styles:
            _add(result, "depop_specifics.style", "Depop style tags are required")
        elif len(styles) > 3:
            _add(result, "depop_specifics.style", "Depop allows only 3 style tags")
        for style in styles:
            if style not in VALID_DEPOP_STYLE:
                _add(result, "depop_specifics.style", f"Depop style '{style}' is not a current dropdown value")
                break
        occasions = _as_list(depop.get("occasion"))
        if not occasions:
            _add(result, "depop_specifics.occasion", "Depop occasion tags are required")
        for occasion in occasions:
            if occasion not in VALID_DEPOP_OCCASION:
                _add(result, "depop_specifics.occasion", f"Depop occasion '{occasion}' is not a current dropdown value")
                break
        parcel = _text(depop.get("parcelSize") or depop.get("parcel_size"))
        if parcel and not _allowed_match(parcel, VALID_DEPOP_PARCEL):
            _add(result, "depop_specifics.parcelSize", "Depop parcel size is not a current dropdown value")
        elif not parcel:
            _add(result, "depop_specifics.parcelSize", "Depop parcel size is required")
        grouping = _text(depop.get("sizeGrouping") or depop.get("size_grouping"))
        size_type = _text(payload.get("sizeType"))
        if grouping:
            if grouping.casefold() in {DNA_VALUE.casefold(), "n/a", "na", "none"}:
                pass
            elif grouping not in VALID_DEPOP_GROUPING:
                _add(result, "depop_specifics.sizeGrouping", "Regular items must not use a Depop size grouping")
            elif size_type.lower() == "regular":
                _add(result, "depop_specifics.sizeGrouping", "Regular items must not use a Depop size grouping")
        elif size_type.lower() in {"petite", "plus", "plus size", "tall", "maternity"}:
            _add(result, "depop_specifics.sizeGrouping", "Depop size grouping is required for non-regular sizing")
        materials = _as_list(depop.get("material"))
        for material in materials:
            if material not in VALID_DEPOP_MATERIAL:
                _add(result, "depop_specifics.material", f"Depop material '{material}' is not a current dropdown value")
                break
        if not materials:
            _add(
                result,
                "depop_specifics.material",
                "Depop material evidence is missing. Keep material blank and state the gap in the description.",
                warning=True,
            )

    etsy = _mapping(payload.get("etsy_specifics"))
    if payload.get("etsy_specifics") is not None and etsy is None:
        _add(result, "etsy_specifics", "Etsy specifics must be an object")
        etsy = {}
    etsy = etsy or {}
    if "etsy" in selected_set:
        who = _etsy_who_raw(etsy)
        what = _etsy_what_raw(etsy)
        if not who:
            _add(result, "etsy_specifics.who_made", "Etsy who-made is required")
        elif who not in VALID_ETSY_WHO:
            _add(result, "etsy_specifics.who_made", "Etsy who-made is not a current dropdown value")
        if not what:
            _add(result, "etsy_specifics.what_is", "Etsy what-is is required")
        elif what not in VALID_ETSY_WHAT:
            _add(result, "etsy_specifics.what_is", "Etsy what-is is not a current dropdown value")
        when_options = _etsy_when_options()
        when = _etsy_when_raw(etsy, payload)
        dropdown_when = _resolve_etsy_when(when, when_options) if when else ""
        if dropdown_when and dropdown_when != when:
            etsy = dict(etsy)
            etsy["when_made"] = dropdown_when
            payload["etsy_specifics"] = etsy
            when = dropdown_when
        if not when:
            _add(result, "etsy_specifics.when_made", "Etsy when-made is required")
        tags = _as_list(etsy.get("tags"))
        if len(tags) > 13:
            _add(result, "etsy_specifics.tags", "Etsy allows at most 13 tags")
        materials = _as_list(etsy.get("materials"))
        if len(materials) > 10:
            _add(result, "etsy_specifics.materials", "Etsy allows at most 10 materials")
        handmade = who in {"I did", "A member of my shop"}
        vintage_or_eligible = _etsy_when_is_vintage_or_handmade(dropdown_when, who, what)
        digital_item = "digital" in _etsy_listing_type(etsy).lower() or "digital" in what.lower()
        commercial_maker = who in {"", "Another company or person"}
        modern_resale = commercial_maker and (not when or _etsy_when_is_modern(dropdown_when))
        if modern_resale and not vintage_or_eligible and not handmade and not digital_item:
            _add(
                result,
                "etsy_specifics.when_made",
                "This modern mass-produced item is not Etsy eligible. Deselect Etsy or use a vintage, handmade, craft-supply, or digital listing.",
                warning=True,
            )
        if not digital_item:
            for key in ETSY_CATEGORY_OPTIONAL_KEYS:
                if key == "pattern":
                    # fabricPattern is the Vendoo fill key; pattern is an alias.
                    if not _ebay_optional_blank(_ebay_optional_raw(etsy, "fabricPattern")):
                        continue
                if key == "fabricPattern":
                    if not _ebay_optional_blank(_ebay_optional_raw(etsy, "pattern")):
                        continue
                value = _ebay_optional_raw(etsy, key)
                if _ebay_optional_blank(value):
                    _add(
                        result,
                        f"etsy_specifics.{key}",
                        f"Etsy optional '{key}' must be filled (or Does Not Apply only when it truly does not apply)",
                    )
                    continue
                text = _text(value) if not isinstance(value, (list, tuple)) else ",".join(str(v) for v in value)
                is_dna = text.casefold() in {
                    DNA_VALUE.casefold(), "n/a", "na", "none", "does not apply", "----",
                }
                if is_dna and key not in ETSY_OPTIONAL_DNA_KEYS:
                    _add(
                        result,
                        f"etsy_specifics.{key}",
                        f"Etsy '{key}' applies to this item — use a real value, not Does Not Apply",
                    )

    unsupported = [name for name in selected if name.lower() not in FILLABLE_MARKETPLACES]
    for name in unsupported:
        _add(
            result,
            f"marketplaces.{name}",
            f"{name.title()} is selected but is not supported for Send to Vendoo. Deselect it before sending.",
        )

    return result
