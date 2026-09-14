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


def _allowed_match(value: str, allowed: Iterable[str]) -> bool:
    needle = value.strip().lower()
    if not needle:
        return False
    for option in allowed:
        option_text = str(option).strip().lower()
        if not option_text or option_text == "----":
            continue
        base_option = option_text.split("(", 1)[0].strip()
        if needle == option_text or needle == base_option:
            return True
    return False


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


def validate_listing(
    data: dict,
    required_photo_count: Optional[int] = None,
    *,
    require_photos: bool = True,
    selected_marketplaces: list[str] | None = None,
) -> ValidationResult:
    result = ValidationResult(valid=True)
    payload = data if isinstance(data, dict) else {}
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
        season = _text(ebay.get("season"))
        if season and not _allowed_match(season, VALID_EBAY_SEASONS):
            _add(result, "ebay_specifics.season", "eBay Season must be Spring, Summer, Fall, or Winter")
        ebay_size = _text(ebay.get("size"))
        if size and ebay_size and ebay_size.lower() != size.lower():
            _add(result, "ebay_specifics.size", "eBay size must match the general size")
        care = _text(ebay.get("garmentCare"))
        if care and _evidence_unknown(description, "care tag is not shown", "garment care", "unverified"):
            if "unknown" in description.lower() or "not shown" in description.lower() or "unverified" in description.lower():
                _add(result, "ebay_specifics.garmentCare", "Do not invent garment care when the care tag is not shown")
        material = _text(ebay.get("material"))
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
        if len(styles) > 3:
            _add(result, "depop_specifics.style", "Depop allows only 3 style tags")
        for style in styles:
            if style not in VALID_DEPOP_STYLE:
                _add(result, "depop_specifics.style", f"Depop style '{style}' is not a current dropdown value")
                break
        materials = _as_list(depop.get("material"))
        for material in materials:
            if material not in VALID_DEPOP_MATERIAL:
                _add(result, "depop_specifics.material", f"Depop material '{material}' is not a current dropdown value")
                break
        occasions = _as_list(depop.get("occasion"))
        for occasion in occasions:
            if occasion not in VALID_DEPOP_OCCASION:
                _add(result, "depop_specifics.occasion", f"Depop occasion '{occasion}' is not a current dropdown value")
                break
        parcel = _text(depop.get("parcelSize") or depop.get("parcel_size"))
        if parcel and not _allowed_match(parcel, VALID_DEPOP_PARCEL):
            _add(result, "depop_specifics.parcelSize", "Depop parcel size is not a current dropdown value")
        grouping = _text(depop.get("sizeGrouping") or depop.get("size_grouping"))
        size_type = _text(payload.get("sizeType"))
        if grouping:
            if grouping not in VALID_DEPOP_GROUPING:
                _add(result, "depop_specifics.sizeGrouping", "Regular items must not use a Depop size grouping")
            elif size_type.lower() == "regular":
                _add(result, "depop_specifics.sizeGrouping", "Regular items must not use a Depop size grouping")

    etsy = _mapping(payload.get("etsy_specifics"))
    if payload.get("etsy_specifics") is not None and etsy is None:
        _add(result, "etsy_specifics", "Etsy specifics must be an object")
        etsy = {}
    etsy = etsy or {}
    if "etsy" in selected_set:
        who = _text(etsy.get("who_made") or etsy.get("whoMade"))
        what = _text(etsy.get("what_is") or etsy.get("whatIs"))
        when = _text(etsy.get("when_made") or etsy.get("whenMade"))
        if not who:
            _add(result, "etsy_specifics.who_made", "Etsy who-made is required")
        elif who not in VALID_ETSY_WHO:
            _add(result, "etsy_specifics.who_made", "Etsy who-made is not a current dropdown value")
        if not what:
            _add(result, "etsy_specifics.what_is", "Etsy what-is is required")
        elif what not in VALID_ETSY_WHAT:
            _add(result, "etsy_specifics.what_is", "Etsy what-is is not a current dropdown value")
        when_options = _etsy_when_options()
        if not when:
            _add(result, "etsy_specifics.when_made", "Etsy when-made is required")
        elif when_options and not _allowed_match(when, when_options):
            _add(result, "etsy_specifics.when_made", "Etsy when-made is not a current dropdown value")
        tags = _as_list(etsy.get("tags"))
        if len(tags) > 13:
            _add(result, "etsy_specifics.tags", "Etsy allows at most 13 tags")
        materials = _as_list(etsy.get("materials"))
        if len(materials) > 10:
            _add(result, "etsy_specifics.materials", "Etsy allows at most 10 materials")
        handmade = who in {"I did", "A member of my shop"}
        vintage_or_eligible = _etsy_when_is_vintage_or_handmade(when, who, what)
        digital_item = "digital" in _etsy_listing_type(etsy).lower() or "digital" in what.lower()
        commercial_maker = who in {"", "Another company or person"}
        modern_resale = commercial_maker and (not when or _etsy_when_is_modern(when))
        if modern_resale and not vintage_or_eligible and not handmade and not digital_item:
            _add(
                result,
                "etsy_specifics.when_made",
                "This modern mass-produced item is not Etsy eligible. Deselect Etsy or use a vintage, handmade, craft-supply, or digital listing.",
            )

    unsupported = [name for name in selected if name.lower() not in FILLABLE_MARKETPLACES]
    for name in unsupported:
        _add(
            result,
            f"marketplaces.{name}",
            f"{name.title()} is selected but is not supported for Send to Vendoo. Deselect it before sending.",
        )

    return result
