"""Depop listing attributes: parcel size, tags, materials, and category optional defaults."""

from __future__ import annotations

import re
from typing import Any

from vendoo_studio.models.ebay_fields import (
    ebay_optional_blank,
    ebay_season_haystack,
    infer_ebay_season,
)
from vendoo_studio.models.listing_values import (
    as_list,
    canonical_option,
    text_value,
)
from vendoo_studio.models.schema import (
    VALID_DEPOP_MATERIAL,
    VALID_DEPOP_OCCASION,
    VALID_DEPOP_STYLE,
)

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
# Last-resort pads when listing text yields fewer than 3 style cues.
DEPOP_STYLE_FALLBACKS = ("Casual", "Minimalist", "Indie")
DEPOP_DEFAULT_OCCASIONS = ("Casual", "Going out", "Vacation")

# Keyword cues → Depop style labels. Scores accumulate; top hits win.
DEPOP_STYLE_CUES: dict[str, tuple[str, ...]] = {
    "Streetwear": (
        r"\bstreetwear\b", r"\bstreet\s*style\b",
        r"\bgraphic\s*(?:tee|t[\s-]?shirt|top)\b", r"\bhype(?:beast)?\b",
        r"\boversized\s+(?:hoodie|tee|sweat)\b",
    ),
    "Sportswear": (
        r"\bsportswear\b", r"\bathletic\b", r"\bactivewear\b", r"\bworkout\b",
        r"\bleggings?\b", r"\btrack\s*(?:pant|jacket|suit)\b", r"\bjoggers?\b",
        r"\bsporty\b",
    ),
    "Loungewear": (
        r"\bloungewear\b", r"\blounge\b", r"\bpajamas?\b", r"\bpyjamas?\b",
        r"\bsweatpants?\b", r"\brobe\b", r"\bsleepwear\b",
    ),
    "Goth": (r"\bgoth(?:ic)?\b", r"\bvampire\b", r"\bbatwing\b"),
    "Retro": (
        r"\bretro\b", r"\bvintage\b", r"\bdeadstock\b",
        r"\b(?:50|60|70|80|90)s\b", r"\bthrowback\b",
    ),
    "Boho": (
        r"\bboho\b", r"\bbohemian\b", r"\bpeasant\b", r"\bfloral\b",
        r"\bflower(?:ed|s)?\b", r"\bfringe\b", r"\bembroider(?:ed|y)\b",
        r"\btassels?\b",
    ),
    "Western": (
        r"\bwestern\b", r"\bcowboy\b", r"\bcowgirl\b", r"\brodeo\b",
        r"\bfringe\s+(?:jacket|vest)\b",
    ),
    "Indie": (r"\bindie\b", r"\balternative\b", r"\bthrift(?:ed|y)?\b"),
    "Skater": (r"\bskater\b", r"\bskate\b", r"\bskateboard\b"),
    "Rave": (r"\brave\b", r"\bfestival\b", r"\bneon\b", r"\bedm\b"),
    "Costume": (r"\bcostume\b", r"\bhalloween\b", r"\bdress[\s-]*up\b"),
    "Cosplay": (r"\bcosplay\b", r"\banime\b", r"\bmanga\b"),
    "Grunge": (r"\bgrunge\b", r"\bdistressed\b", r"\bflannel\b"),
    "Emo": (r"\bemo\b",),
    "Minimalist": (
        r"\bminimalist\b", r"\bminimal\b", r"\bclean\s*line\b",
        r"\bbasic\b", r"\bplain\b",
    ),
    "Preppy": (
        r"\bpreppy\b", r"\bprep\b", r"\bcollegiate\b", r"\bplaid\b",
        r"\btweed\b", r"\bpolo\b", r"\bargyle\b",
    ),
    "Avant Garde": (r"\bavant[\s-]*garde\b", r"\bexperimental\b", r"\basymmetric\b"),
    "Punk": (r"\bpunk\b", r"\bstudded\b", r"\bspiked\b", r"\banarchy\b"),
    "Glam": (
        r"\bglam\b", r"\bglitter\b", r"\bsequin\b", r"\bmetallic\b",
        r"\brhinestone\b", r"\bparty\s*dress\b",
    ),
    "Regency": (r"\bregency\b", r"\bbridgerton\b", r"\bempire\s*waist\b"),
    "Casual": (
        r"\bcasual\b", r"\beveryday\b", r"\brelaxed\b", r"\btunic\b",
        r"\bblouse\b", r"\btee\b", r"\bt[\s-]?shirt\b",
        r"\bjeans?\b", r"\bdenim\b",
    ),
    "Utility": (
        r"\butility\b", r"\btechwear\b", r"\bcargo\b", r"\bworkwear\b",
        r"\btactical\b",
    ),
    "Futuristic": (r"\bfuturistic\b", r"\bcyber\b", r"\bmetallic\s*foil\b"),
    "Cottage": (r"\bcottage(?:core)?\b", r"\brural\b"),
    "Fairy": (r"\bfairy(?:core)?\b", r"\bethereal\b", r"\bwhimsical\b"),
    "Kidcore": (r"\bkidcore\b", r"\bchildlike\b"),
    "Y2K": (r"\by2k\b", r"\b2000s\b", r"\blow[\s-]*rise\b"),
    "Biker": (
        r"\bbiker\b", r"\bmoto(?:rcycle)?\b", r"\bleather\s*jacket\b",
        r"\bmoto\s*jacket\b",
    ),
    "Gorpcore": (
        r"\bgorpcore\b", r"\bhiking\b", r"\bpatagonia\b",
        r"\bnorth\s*face\b",
    ),
    "Twee": (r"\btwee\b", r"\bquirky\b", r"\bkitschy\b"),
    "Coquette": (r"\bcoquette\b", r"\bballetcore\b"),
    "Whimsygoth": (r"\bwhimsygoth\b", r"\bwhimsy\s*goth\b"),
}

VALID_DEPOP_GROUPING = frozenset({"Maternity", "Petite", "Plus size", "Tall"})
VALID_DEPOP_PARCEL = (
    "Extra extra small",
    "Extra small",
    "Small",
    "Medium",
    "Large",
    "Extra large",
)


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


def infer_depop_styles(
    listing: dict | None = None,
    *,
    ebay: dict | None = None,
    limit: int = 3,
    exclude: list[str] | tuple[str, ...] | set[str] | frozenset[str] | None = None,
) -> list[str]:
    """Pick up to ``limit`` Depop styles from listing text (never a fixed Casual/Retro/Boho trio)."""
    listing = listing if isinstance(listing, dict) else {}
    if not isinstance(ebay, dict):
        raw = listing.get("ebay_specifics")
        ebay = raw if isinstance(raw, dict) else {}
    hay = ebay_season_haystack(listing, ebay)
    blocked = {str(item) for item in (exclude or ()) if item}
    scores: dict[str, int] = {name: 0 for name in VALID_DEPOP_STYLE}

    # Exact Depop label in the haystack is a strong signal.
    for style in VALID_DEPOP_STYLE:
        if style in blocked:
            continue
        if re.search(rf"\b{re.escape(style)}\b", hay, flags=re.I):
            scores[style] += 3

    for style, patterns in DEPOP_STYLE_CUES.items():
        if style in blocked or style not in scores:
            continue
        for pattern in patterns:
            if re.search(pattern, hay, flags=re.I):
                scores[style] += 1

    # eBay style / theme / pattern fields often carry the best single cue.
    for key in ("style", "theme", "pattern", "features", "type"):
        for part in as_list(ebay.get(key)):
            text = text_value(part)
            if not text:
                continue
            hit = canonical_option(text, VALID_DEPOP_STYLE)
            if hit and hit not in blocked:
                scores[hit] += 2
            folded = text.casefold()
            for style, patterns in DEPOP_STYLE_CUES.items():
                if style in blocked:
                    continue
                if any(re.search(pattern, folded, flags=re.I) for pattern in patterns):
                    scores[style] += 1

    ranked = sorted(
        (name for name, score in scores.items() if score > 0 and name not in blocked),
        key=lambda name: (-scores[name], name),
    )
    picked = ranked[:limit]
    if len(picked) >= limit:
        return picked
    fallbacks = tuple(name for name in DEPOP_STYLE_FALLBACKS if name not in blocked)
    return _pad_depop_tags(picked, fallbacks, limit=limit)


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


def _map_depop_material(value: str) -> str | None:
    raw = text_value(value)
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
    hit = canonical_option(raw, VALID_DEPOP_MATERIAL)
    if hit:
        return hit
    cleaned = re.sub(r"\b(?:blend|pure|100%)\b", "", raw, flags=re.I).strip(" ,")
    return canonical_option(cleaned, VALID_DEPOP_MATERIAL) if cleaned else None


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
    hay = ebay_season_haystack(listing, ebay)

    def set_key(key: str, value: Any) -> None:
        nonlocal depop, changed
        current = depop.get(key)
        if key in {"style", "occasion", "material"}:
            if as_list(current):
                return
        elif not ebay_optional_blank(current):
            return
        depop[key] = value
        changed = True

    if ebay_optional_blank(depop.get("source")):
        source = "Vintage" if re.search(r"\b(?:vintage|deadstock|y2k|90s|80s|70s)\b", hay) else "Preloved"
        set_key("source", source)

    if ebay_optional_blank(depop.get("age")):
        age = "Modern"
        for decade in ("50s", "60s", "70s", "80s", "90s"):
            if re.search(rf"\b{decade}\b", hay):
                age = decade
                break
        if age == "Modern" and re.search(r"\by2k\b", hay):
            age = "y2k"
        set_key("age", age)

    styles = as_list(depop.get("style"))
    mapped: list[str] = []
    for style in styles:
        hit = canonical_option(style, VALID_DEPOP_STYLE)
        if hit and hit not in mapped:
            mapped.append(hit)
    if len(mapped) < 3:
        inferred = infer_depop_styles(listing, ebay=ebay, limit=3, exclude=mapped)
        padded = _pad_depop_tags(mapped, tuple(inferred) + DEPOP_STYLE_FALLBACKS, limit=3)
        if padded != styles:
            depop["style"] = padded
            changed = True

    occasions = as_list(depop.get("occasion"))
    occasion_hits = [canonical_option(occasion, VALID_DEPOP_OCCASION) for occasion in occasions]
    if not occasions:
        mapped = []
        ebay_occ = ebay.get("occasion") if isinstance(ebay, dict) else None
        for occasion in as_list(ebay_occ):
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
            hit = mapped_value or canonical_option(str(occasion), VALID_DEPOP_OCCASION)
            if hit and hit not in mapped:
                mapped.append(hit)
        season = text_value(ebay.get("season") if isinstance(ebay, dict) else "") or infer_ebay_season(listing, ebay=ebay)
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
    parcel = text_value(depop.get("parcelSize") or depop.get("parcel_size"))
    from_weight = _infer_depop_parcel_size(listing)
    if from_weight:
        if parcel != from_weight or "parcel_size" in depop:
            depop["parcelSize"] = from_weight
            depop.pop("parcel_size", None)
            changed = True
    elif not parcel:
        set_key("parcelSize", "Medium")
        depop.pop("parcel_size", None)

    size_type = text_value(listing.get("sizeType") or ebay.get("sizeType")).casefold()
    grouping = text_value(depop.get("sizeGrouping") or depop.get("size_grouping"))
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

    if not as_list(depop.get("material")):
        candidates = [
            *as_list(depop.get("material")),
            *as_list(ebay.get("material") if isinstance(ebay, dict) else None),
            *as_list(ebay.get("fabricType") if isinstance(ebay, dict) else None),
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
