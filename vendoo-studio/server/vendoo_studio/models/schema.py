from __future__ import annotations

from typing import Optional, Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


VALID_CONDITIONS = frozenset((
    "New With Tags/Box",
    "New Without Tags/Box",
    "New With Imperfections",
    "Pre-Owned - Excellent",
    "Pre-Owned - Good",
    "Pre-Owned - Fair",
    "Poor (Major flaws)",
))

PACKAGE_DIMS_PATTERN = r"^\d+(\.\d+)?\s*x\s*\d+(\.\d+)?\s*x\s*\d+(\.\d+)?$"


class EbaySpecifics(BaseModel):
    model_config = ConfigDict(extra="allow")
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
    source: Optional[str] = None
    age: Optional[str] = None
    style: Optional[list[str] | str] = None
    material: Optional[list[str] | str] = None
    occasion: Optional[list[str] | str] = None
    size_grouping: Optional[str] = None


class EtsySpecifics(BaseModel):
    model_config = ConfigDict(extra="allow")
    who_made: Optional[str] = None
    what_is: Optional[str] = None
    when_made: Optional[str] = None
    section: Optional[str] = None
    materials: Optional[list[str] | str] = None
    tags: Optional[list[str] | str] = None
    category_specifics: Optional[dict[str, str]] = None


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
            lv = v.lower()
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
