from __future__ import annotations

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
    "who made": "who_made",
    "what is it": "what_is",
    "when made": "when_made",
    "original price": "originalPrice",
    "shipping label": "shippingLabel",
    "style tags": "styleTags",
}


CATEGORY_NORMALIZATIONS: dict[str, dict[str, str]] = {
    "general": {
        "women's shirts & blouses": "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops",
        "women's t-shirts": "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops",
        "women's tops": "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops",
        "men's t-shirts": "Clothing, Shoes & Accessories > Men > Men's Clothing > Shirts > T-Shirts",
        "men's shirts": "Clothing, Shoes & Accessories > Men > Men's Clothing > Shirts",
    },
}


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

    def normalize_category(self, marketplace: str, category: str) -> tuple[str, bool]:
        marketplace_norms = CATEGORY_NORMALIZATIONS.get(marketplace, {})
        key = category.strip().lower()
        if key in marketplace_norms:
            return (marketplace_norms[key], True)
        return (category, False)

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
