from __future__ import annotations

import re

from sqlalchemy.orm import Session

from vendoo_studio.repositories.queries import RegistryRepo, _normalize_label


CANONICAL_DEFAULTS: dict[str, dict[str, str]] = {
    "mercari": {
        "shipping label": "USPS Ground Advantage",
    },
    "poshmark": {
        "original price": "0",
    },
    "depop": {
        "brand": "Other",
    },
}

LEARNED_MARKETPLACES = ("ebay", "etsy", "poshmark", "mercari", "depop")

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
    r"\bdresses?\b|\bpants?\b|\bjeans?\b|\bskirts?\b|\bshorts?\b|\bjackets?\b|"
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
_BLOUSE_RE = re.compile(r"\bblouses?\b", re.I)
_POSHMARK_ROOT_RE = re.compile(r"^(men|women|kids|pets|home|electronics)\s*>", re.I)


def map_poshmark_category_path(category: str, listing: dict | None = None) -> str:
    """Map a Vendoo/listing category onto a selectable Poshmark path."""
    listing = listing if isinstance(listing, dict) else {}
    raw = (category or "").strip() or str(listing.get("category_path") or "").strip()
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
            if not stale_women and not stale_men:
                return explicit_path

    if _POSHMARK_ROOT_RE.search(raw):
        return raw
    if _NON_TOP_RE.search(_path_leaf(raw)):
        return raw

    ebay = listing.get("ebay_specifics") if isinstance(listing.get("ebay_specifics"), dict) else {}
    sleeve = ""
    if isinstance(ebay, dict):
        sleeve = str(ebay.get("sleeveLength") or "")
    haystack = f"{raw} {_listing_text(listing)} {sleeve} {listing.get('sleeveLength') or ''}"
    gender = _listing_gender(listing, raw)
    is_women = gender == "women"
    is_men = gender == "men"
    if gender is None:
        is_women = bool(_WOMEN_RE.search(haystack))
        is_men = bool(_MEN_RE.search(haystack)) and not is_women
    is_tee = bool(_TEE_RE.search(haystack))
    is_blouse = bool(_BLOUSE_RE.search(haystack)) and not is_tee
    long_sleeve = bool(_LONG_SLEEVE_RE.search(haystack))
    if is_men and is_tee:
        return POSHMARK_MEN_LONG_TEE if long_sleeve else POSHMARK_MEN_SHORT_TEE
    if is_women and is_tee:
        return POSHMARK_WOMEN_LONG_TEE if long_sleeve else POSHMARK_WOMEN_SHORT_TEE
    if is_women and is_blouse:
        return POSHMARK_WOMEN_BLOUSE
    return raw


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
                if _has_value(specifics.get(json_key)):
                    continue
                if json_key in specifics and specifics.get(json_key) == "":
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
    return True


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
