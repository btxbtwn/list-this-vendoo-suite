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
DEPOP_DEFAULT_STYLES = ("Casual", "Retro", "Boho")
DEPOP_DEFAULT_OCCASIONS = ("Casual", "Going out", "Vacation")

VALID_DEPOP_GROUPING = frozenset({"Maternity", "Petite", "Plus size", "Tall"})
VALID_DEPOP_PARCEL = (
    "Extra extra small",
    "Extra small",
    "Small",
    "Medium",
    "Large",
    "Extra large",
)


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
    style_hits = [canonical_option(style, VALID_DEPOP_STYLE) for style in styles]
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
