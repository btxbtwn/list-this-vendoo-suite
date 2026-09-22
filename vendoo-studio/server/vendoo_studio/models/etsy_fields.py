"""Etsy listing attributes: when/who/what made and category optional defaults."""

from __future__ import annotations

import re
from typing import Any

from vendoo_studio.models.ebay_fields import (
    ebay_optional_blank,
    ebay_optional_raw,
    ebay_season_haystack,
)
from vendoo_studio.models.listing_values import (
    DNA_VALUE,
    as_mapping,
    canonical_option,
    dropdown_field_options,
    dropdown_options,
    infer_known_option,
    normalized_option_key,
    text_value,
)
from vendoo_studio.models.schema import (
    _scalar_text,
)

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
ETSY_APPAREL_CUES = {
    "clothingStyle": {
        "Streetwear": (r"\bstreetwear\b", r"\bgraphic\s*(?:tee|t[\s-]?shirt)\b", r"\bskate\b"),
        "Athletic": (r"\bathletic\b", r"\bworkout\b", r"\bactivewear\b", r"\bgym\b"),
        "Boho & hippie": (r"\bboho\b", r"\bbohemian\b", r"\bhippie\b", r"\bfloral\b"),
        "Gothic": (r"\bgoth(?:ic)?\b",),
        "Preppy": (r"\bpreppy\b", r"\bpolo\b"),
        "Rave": (r"\brave\b", r"\bfestival\b"),
        "Rocker": (r"\brocker\b", r"\bpunk\b"),
        "Utility": (r"\butility\b", r"\bcargo\b"),
        "Military": (r"\bmilitary\b",),
        "Minimalist": (r"\bminimalist\b", r"\bminimal\b", r"\bplain\b", r"\bbasic\b"),
    },
    "neckline": {"V-neck": (r"\bv[\s-]*neck\b",), "Henley": (r"\bhenley\b",), "Crew": (r"\bcrew(?:\s*neck)?\b", r"\btee\b")},
    "closure": {"Pullover": (r"\bpullover\b", r"\btee\b", r"\bt[\s-]?shirt\b"), "Button": (r"\bbutton(?:[\s-]*up|[\s-]*down)?\b",), "Zipper": (r"\bzip(?:per|[\s-]*up)?\b",)},
    "pattern": {"Floral": (r"\bfloral\b",), "Striped": (r"\bstripe[ds]?\b",), "Plaid": (r"\bplaid\b",), "Solid": (r"\bsolid\b", r"\bplain\b")},
    "holiday": {"Christmas": (r"\bchristmas\b", r"\bxmas\b"), "Halloween": (r"\bhalloween\b",), "Thanksgiving": (r"\bthanksgiving\b",), "Valentine's Day": (r"\bvalentine\b",), "Easter": (r"\beaster\b",)},
    "occasion": {"Wedding": (r"\bwedding\b",), "Birthday": (r"\bbirthday\b",), "Graduation": (r"\bgraduation\b",), "Engagement": (r"\bengagement\b",), "Bachelor party": (r"\bbachelor\b",), "Baby shower": (r"\bbaby\s*shower\b",), "Anniversary": (r"\banniversary\b",), "LGBTQ pride": (r"\bpride\b",)},
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

VALID_ETSY_WHO = frozenset({
    "Another company or person",
    "A member of my shop",
    "I did",
})
VALID_ETSY_WHAT = frozenset({
    "A finished product",
    "A supply or tool to make things",
})

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


def etsy_when_options() -> list[str]:
    forms = (dropdown_options().get("forms") or {}).get("etsy") or {}
    values = forms.get("whenMade") or []
    return [str(item) for item in values if str(item).strip()]


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


def etsy_when_raw(etsy: dict[str, Any], listing: dict[str, Any] | None = None) -> str:
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


def _etsy_choice_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


# Vendoo stores who/what as codes (someone_else, "0"), which come back on
# import; the model also paraphrases the labels. Both map to the dropdown label.
ETSY_WHO_ALIASES = {
    **{_etsy_choice_key(label): label for label in VALID_ETSY_WHO},
    "someone else": "Another company or person",
    "another company": "Another company or person",
    "collective": "A member of my shop",
    "i did": "I did",
}
ETSY_WHAT_ALIASES = {
    **{_etsy_choice_key(label): label for label in VALID_ETSY_WHAT},
    "0": "A finished product",
    "false": "A finished product",
    "finished product": "A finished product",
    "1": "A supply or tool to make things",
    "true": "A supply or tool to make things",
    "supply or tool to make things": "A supply or tool to make things",
    "a supply or tool": "A supply or tool to make things",
    "supply": "A supply or tool to make things",
}


def _etsy_choice(etsy: dict[str, Any], keys: tuple[str, ...], aliases: dict[str, str]) -> str:
    for key in keys:
        text = _scalar_text(etsy.get(key)) if key in etsy else None
        if text:
            return aliases.get(_etsy_choice_key(text), text)
    return ""


def etsy_who_raw(etsy: dict[str, Any]) -> str:
    return _etsy_choice(
        etsy, ("who_made", "whoMade", "whoMadeIt", "whoMadeIt?", "Who Made It?"), ETSY_WHO_ALIASES
    )


def etsy_what_raw(etsy: dict[str, Any]) -> str:
    return _etsy_choice(
        etsy, ("what_is", "whatIs", "whatIsIt", "whatIsIt?", "What Is It?"), ETSY_WHAT_ALIASES
    )


def resolve_etsy_when(raw: str, options: list[str]) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    mapped = _canonical_etsy_when(text)
    allowed = options or [mapped, DEFAULT_ETSY_WHEN]
    for candidate in (mapped, text):
        hit = canonical_option(candidate, allowed)
        if hit:
            return hit
    if options:
        mapped_key = normalized_option_key(mapped or text)
        for option in sorted(options, key=lambda item: len(normalized_option_key(item)), reverse=True):
            option_key = normalized_option_key(option)
            if option_key and len(option_key) >= 4 and (
                option_key in mapped_key or mapped_key in option_key
            ):
                return option
        for option in options:
            if "2010" in option:
                return option
        return options[0]
    return mapped or DEFAULT_ETSY_WHEN


def etsy_when_is_vintage_or_handmade(when_made: str, who_made: str, what_is: str) -> bool:
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


def etsy_listing_type(etsy: dict[str, Any] | None) -> str:
    specs = etsy or {}
    return text_value(specs.get("listing_type") or specs.get("listingType"))


def is_etsy_digital_listing(payload: dict[str, Any]) -> bool:
    etsy = as_mapping(payload.get("etsy_specifics")) or {}
    listing_type = etsy_listing_type(etsy).lower()
    if "digital" in listing_type:
        return True
    what = text_value(etsy.get("what_is") or etsy.get("whatIsIt")).lower()
    return "digital" in what


def etsy_when_is_modern(when_made: str) -> bool:
    when = when_made.lower()
    if not when:
        return True
    return any(token in when for token in MODERN_ETSY_WHEN)


def _infer_etsy_sleeve_length(listing: dict | None, etsy: dict | None, ebay: dict | None = None) -> str:
    hay = ebay_season_haystack(listing, ebay if isinstance(ebay, dict) else None)
    if isinstance(etsy, dict):
        hay = f"{hay} {text_value(etsy.get('type'))} {text_value(etsy.get('sleeveLength'))}".casefold()
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
        if ebay_optional_blank(ebay_optional_raw(etsy, key)):
            etsy[key] = value
            nested = etsy.get("category_specifics")
            if isinstance(nested, dict) and key in nested and ebay_optional_blank(nested.get(key)):
                nested = dict(nested)
                nested[key] = value
                etsy["category_specifics"] = nested
            changed = True

    # Prefer eBay apparel specifics when Etsy rows are still empty.
    ebay_map = {
        "closure": text_value(ebay_optional_raw(ebay, "closure")),
        "collarStyle": text_value(ebay_optional_raw(ebay, "collarStyle")),
        "sleeveLength": text_value(ebay_optional_raw(ebay, "sleeveLength")),
        "neckline": text_value(ebay_optional_raw(ebay, "neckline")),
        "pattern": text_value(ebay_optional_raw(ebay, "pattern")),
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
        if key == "fabricPattern":
            continue
        source = ebay_map.get(key) if key in {"closure", "neckline", "pattern"} else ""
        if source and key == "pattern":
            options = dropdown_field_options("etsy", "fabricPattern", "pattern")
            hit = canonical_option(source, options) if options else source
            set_key(key, hit or source)
            continue
        if source and key in {"closure", "neckline"}:
            options = dropdown_field_options("etsy", key)
            hit = canonical_option(source, options) if options else source
            set_key(key, hit or source)
            continue
        if ebay_optional_blank(ebay_optional_raw(etsy, key)):
            options = dropdown_field_options(
                "etsy",
                "fabricPattern" if key == "pattern" else key,
                key,
            )
            cues = ETSY_APPAREL_CUES.get("pattern" if key == "pattern" else key)
            hay_early = ebay_season_haystack(listing, ebay)
            value = infer_known_option(hay_early, options or [default], cues=cues, fallback=default) or default
            set_key(key, value)

    if ebay_optional_blank(ebay_optional_raw(etsy, "fabricPattern")):
        pattern = text_value(ebay_optional_raw(etsy, "pattern") or ebay_map.get("pattern") or "")
        if not pattern:
            options = dropdown_field_options("etsy", "fabricPattern", "pattern")
            pattern = infer_known_option(
                ebay_season_haystack(listing, ebay),
                options or ["Solid"],
                cues=ETSY_APPAREL_CUES.get("pattern"),
                fallback="Solid",
            ) or "Solid"
        set_key("fabricPattern", pattern)
    if ebay_optional_blank(ebay_optional_raw(etsy, "pattern")):
        set_key("pattern", text_value(ebay_optional_raw(etsy, "fabricPattern") or "Solid"))

    if ebay_optional_blank(ebay_optional_raw(etsy, "sleeveLength")):
        set_key(
            "sleeveLength",
            ebay_map.get("sleeveLength") or _infer_etsy_sleeve_length(listing, etsy, ebay),
        )

    hay = ebay_season_haystack(listing, ebay)
    if re.search(r"\b(?:streetwear|graphic\s*tee|skate|hip[\s-]*hop)\b", hay):
        if text_value(ebay_optional_raw(etsy, "clothingStyle")).casefold() == "minimalist":
            etsy["clothingStyle"] = "Streetwear"
            changed = True

    for key in ETSY_OPTIONAL_DNA_KEYS:
        if key == "graphic":
            if re.search(r"\b(?:graphic|logo|print|slogan|saying|brand\s*logo)\b", hay):
                if ebay_optional_blank(ebay_optional_raw(etsy, "graphic")):
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
        if key in {"holiday", "occasion"}:
            if ebay_optional_blank(ebay_optional_raw(etsy, key)):
                options = dropdown_field_options("etsy", key)
                hit = infer_known_option(hay, options, cues=ETSY_APPAREL_CUES.get(key))
                if hit:
                    set_key(key, hit)
                    continue
            else:
                continue
        if ebay_optional_blank(ebay_optional_raw(etsy, key)):
            set_key(key, DNA_VALUE)

    if changed:
        listing["etsy_specifics"] = etsy
    return changed
