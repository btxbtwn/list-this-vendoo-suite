from __future__ import annotations

from typing import Any, Optional, Annotated

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


def _scalar_text(value: Any) -> Optional[str]:
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
        if isinstance(data, dict):
            return _coerce_string_map(data, frozenset({"features", "accents"}))
        return data

    type: Optional[str] = None
    department: Optional[str] = None
    sizeType: Optional[str] = None
    size: Optional[str] = None
    brand: Optional[str] = None
    color: Optional[str] = None
    material: Optional[str] = None
    fit: Optional[str] = None
    sleeveLength: Optional[str] = None
    neckline: Optional[str] = None
    closure: Optional[str] = None
    style: Optional[str] = None
    pattern: Optional[str] = None
    features: Optional[list[str] | str] = None
    theme: Optional[str] = None
    season: Optional[str] = None
    occasion: Optional[str] = None
    countryOfOrigin: Optional[str] = None
    fabricType: Optional[str] = None
    vintage: Optional[str] = None
    handmade: Optional[str] = None
    personalize: Optional[str] = None
    garmentCare: Optional[str] = None
    unitQuantity: Optional[str] = None
    unitType: Optional[str] = None
    mpn: Optional[str] = None
    upc: Optional[str] = None
    character: Optional[str] = None
    characterFamily: Optional[str] = None
    performanceActivity: Optional[str] = None
    yearManufactured: Optional[str] = None
    collarStyle: Optional[str] = None
    strapType: Optional[str] = None
    fabricWeight: Optional[str] = None
    sleeveType: Optional[str] = None
    accents: Optional[list[str] | str] = None
    rise: Optional[str] = None
    inseam: Optional[str] = None
    waist: Optional[str] = None


class DepopSpecifics(BaseModel):
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def coerce_values(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return _coerce_string_map(data, frozenset({"style", "material", "occasion"}))
        return data

    source: Optional[str] = None
    age: Optional[str] = None
    style: Optional[list[str] | str] = None
    material: Optional[list[str] | str] = None
    occasion: Optional[list[str] | str] = None
    size_grouping: Optional[str] = None


class EtsySpecifics(BaseModel):
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def coerce_values(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return _coerce_string_map(
                data,
                frozenset({"materials", "tags"}),
                skip_keys=frozenset({"category_specifics"}),
            )
        return data

    who_made: Optional[str] = None
    what_is: Optional[str] = None
    when_made: Optional[str] = None
    section: Optional[str] = None
    materials: Optional[list[str] | str] = None
    tags: Optional[list[str] | str] = None
    category_specifics: Optional[dict[str, str]] = None

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
    categoryPath: list[str] = Field(default_factory=list)
    originalPrice: float = 0


class MercariSpecifics(BaseModel):
    model_config = ConfigDict(extra="allow")
    categoryPath: list[str] = Field(default_factory=list)
    shippingLabel: str = "USPS Ground Advantage"


class ListingSchema(BaseModel):
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    price: float = Field(..., gt=0)
    cost: Optional[float] = None
    quantity: int = Field(default=1, ge=0)
    brand: Optional[str] = None
    condition: Optional[str] = None
    primaryColor: Optional[str] = None
    secondaryColor: Optional[str] = None
    category_path: Optional[str] = None
    size: Optional[str] = None
    sizeType: Optional[str] = None
    size_us: Optional[str] = None
    sku: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    weight_lb: int = Field(default=0, ge=0)
    weight_oz: int = Field(default=8, ge=0)
    package_dimensions_in: Optional[str] = Field(default="13x10x3")
    internal_notes: Optional[str] = None

    ebay_specifics: EbaySpecifics = Field(default_factory=EbaySpecifics)
    poshmark_specifics: PoshmarkSpecifics = Field(default_factory=PoshmarkSpecifics)
    mercari_specifics: MercariSpecifics = Field(default_factory=MercariSpecifics)
    depop_specifics: DepopSpecifics = Field(default_factory=DepopSpecifics)
    etsy_specifics: EtsySpecifics = Field(default_factory=EtsySpecifics)

    @field_validator("condition")
    @classmethod
    def validate_condition(cls, v: Optional[str]) -> Optional[str]:
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
