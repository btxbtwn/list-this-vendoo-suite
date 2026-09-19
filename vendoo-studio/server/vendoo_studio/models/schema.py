from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


VALID_CONDITIONS = frozenset((
    "New With Tags/Box",
    "New Without Tags/Box",
    "New With Imperfections",
    "Pre-Owned - Excellent",
    "Pre-Owned - Good",
    "Pre-Owned - Fair",
    "Poor (Major flaws)",
))

VALID_DEPOP_SOURCE = frozenset((
    "Vintage", "Preloved", "Reworked", "Custom", "Handmade", "Deadstock",
    "Designer", "Repaired",
))
VALID_DEPOP_AGE = frozenset(("Modern", "y2k", "90s", "80s", "70s", "60s", "50s", "Antique"))
VALID_DEPOP_STYLE = frozenset((
    "Streetwear", "Sportswear", "Loungewear", "Goth", "Retro", "Boho",
    "Western", "Indie", "Skater", "Rave", "Costume", "Cosplay", "Grunge",
    "Emo", "Minimalist", "Preppy", "Avant Garde", "Punk", "Glam", "Regency",
    "Casual", "Utility", "Futuristic", "Cottage", "Fairy", "Kidcore", "Y2K",
    "Biker", "Gorpcore", "Twee", "Coquette", "Whimsygoth",
))
VALID_DEPOP_OCCASION = frozenset((
    "Casual", "Festival", "Gifting", "Going out", "Outdoors", "Party",
    "Relaxation", "School", "Ski", "Special Occasion", "Summer", "Vacation",
    "Winter", "Work", "Workout",
))
VALID_DEPOP_MATERIAL = frozenset((
    "Acrylic", "Canvas", "Cashmere", "Corduroy", "Cotton", "Cotton - Organic",
    "Cotton - Recycled", "Crochet", "Denim", "Elastane / Lycra / Spandex",
    "Embellished", "Faux fur", "Faux leather", "Fleece", "Hemp", "Jersey",
    "Knitted", "Lace", "Leather", "Linen", "Lyocell", "Modal", "Nylon",
    "Polyester", "Polyester - Recycled", "Rayon", "Rubber", "Silk", "Suede",
    "Tweed", "Velvet", "Viscose", "Wool",
))

PACKAGE_DIMS_PATTERN = r"^\d+(\.\d+)?\s*x\s*\d+(\.\d+)?\s*x\s*\d+(\.\d+)?$"


def _scalar_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [part for part in (_scalar_text(item) for item in value) if part]
        return parts[-1] if parts else None
    if isinstance(value, dict):
        for key in ("displayName", "label", "name", "value"):
            text = _scalar_text(value.get(key))
            if text:
                return text
        path = value.get("displayPath") or value.get("path")
        if isinstance(path, list):
            return _scalar_text(path)
    return None


def _coerce_string_map(
    values: dict[str, Any],
    list_keys: frozenset[str],
    skip_keys: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in values.items():
        if key in skip_keys:
            out[key] = value
            continue
        if key in list_keys:
            if isinstance(value, list):
                out[key] = [item for item in (_scalar_text(part) for part in value) if item]
            elif isinstance(value, str):
                out[key] = value
            else:
                text = _scalar_text(value)
                out[key] = [text] if text else value
            continue
        if isinstance(value, (list, dict)):
            text = _scalar_text(value)
            out[key] = text if text is not None else value
        else:
            out[key] = value
    return out


class EbaySpecifics(BaseModel):
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def coerce_values(cls, data: Any) -> Any:
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError("must be an object")
        return _coerce_string_map(data, frozenset({"features", "accents"}))

    type: str | None = None
    department: str | None = None
    sizeType: str | None = None
    size: str | None = None
    brand: str | None = None
    color: str | None = None
    material: str | None = None
    fit: str | None = None
    sleeveLength: str | None = None
    neckline: str | None = None
    closure: str | None = None
    style: str | None = None
    pattern: str | None = None
    features: list[str] | str | None = None
    theme: str | None = None
    season: str | None = None
    occasion: str | None = None
    countryOfOrigin: str | None = None
    fabricType: str | None = None
    vintage: str | None = None
    handmade: str | None = None
    personalize: str | None = None
    garmentCare: str | None = None
    unitQuantity: str | None = None
    unitType: str | None = None
    mpn: str | None = None
    upc: str | None = None
    character: str | None = None
    characterFamily: str | None = None
    performanceActivity: str | None = None
    yearManufactured: str | None = None
    collarStyle: str | None = None
    strapType: str | None = None
    fabricWeight: str | None = None
    sleeveType: str | None = None
    accents: list[str] | str | None = None
    rise: str | None = None
    inseam: str | None = None
    waist: str | None = None


class DepopSpecifics(BaseModel):
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def coerce_values(cls, data: Any) -> Any:
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError("must be an object")
        return _coerce_string_map(data, frozenset({"style", "material", "occasion"}))

    source: str | None = None
    age: str | None = None
    style: list[str] | str | None = None
    material: list[str] | str | None = None
    occasion: list[str] | str | None = None
    size_grouping: str | None = None


class EtsySpecifics(BaseModel):
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def coerce_values(cls, data: Any) -> Any:
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError("must be an object")
        return _coerce_string_map(
            data,
            frozenset({"materials", "tags"}),
            skip_keys=frozenset({"category_specifics"}),
        )

    who_made: str | None = None
    what_is: str | None = None
    when_made: str | None = None
    section: str | None = None
    materials: list[str] | str | None = None
    tags: list[str] | str | None = None
    category_specifics: dict[str, str] | None = None

    @field_validator("category_specifics", mode="before")
    @classmethod
    def coerce_category_specifics(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        out: dict[str, str] = {}
        for key, nested in value.items():
            text = nested if isinstance(nested, str) else _scalar_text(nested)
            if text:
                out[str(key)] = text
        return out


class PoshmarkSpecifics(BaseModel):
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def require_object(cls, data: Any) -> Any:
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError("must be an object")
        return data

    categoryPath: list[str] = Field(default_factory=list)
    originalPrice: float = 0


class MercariSpecifics(BaseModel):
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def require_object(cls, data: Any) -> Any:
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError("must be an object")
        return data

    categoryPath: list[str] = Field(default_factory=list)
    shippingLabel: str = "USPS Ground Advantage / 1 - 7 days / $ 5.66 / 0.5 lb"


class ListingSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str = Field(..., min_length=1, max_length=80)
    description: str = Field(..., min_length=1)
    price: float = Field(..., gt=0)
    cost: float | None = None
    quantity: int = Field(default=1, ge=0)
    brand: str | None = None
    condition: str | None = None
    primaryColor: str | None = None
    secondaryColor: str | None = None
    category_path: str | None = None
    size: str | None = None
    sizeType: str | None = None
    size_us: str | None = None
    sku: str | None = None
    department: str | None = None
    tags: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    weight_lb: int | None = Field(default=None, ge=0)
    weight_oz: int | None = Field(default=None, ge=0)
    package_dimensions_in: str | None = None
    internal_notes: str | None = None

    ebay_specifics: EbaySpecifics = Field(default_factory=EbaySpecifics)
    poshmark_specifics: PoshmarkSpecifics = Field(default_factory=PoshmarkSpecifics)
    mercari_specifics: MercariSpecifics = Field(default_factory=MercariSpecifics)
    depop_specifics: DepopSpecifics = Field(default_factory=DepopSpecifics)
    etsy_specifics: EtsySpecifics = Field(default_factory=EtsySpecifics)

    @field_validator("title", "description", mode="before")
    @classmethod
    def strip_required_text(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("cost", "weight_lb", "weight_oz", mode="before")
    @classmethod
    def empty_numeric_to_none(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("condition")
    @classmethod
    def validate_condition(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in VALID_CONDITIONS:
            lv = v.lower().replace("_", " ").replace("-", " ")
            if "preowned" in lv.replace(" ", "") or "pre owned" in lv:
                if "excellent" in lv or "like new" in lv:
                    return "Pre-Owned - Excellent"
                if "fair" in lv:
                    return "Pre-Owned - Fair"
                return "Pre-Owned - Good"
            if "good" in lv:
                return "Pre-Owned - Good"
            if "poor" in lv:
                return "Poor (Major flaws)"
            if "excellent" in lv or "like new" in lv:
                return "Pre-Owned - Excellent"
            if "fair" in lv:
                return "Pre-Owned - Fair"
            if "imperfection" in lv:
                return "New With Imperfections"
            if "new" in lv and "tag" in lv:
                return "New With Tags/Box"
            if "new" in lv:
                return "New Without Tags/Box"
        return v
