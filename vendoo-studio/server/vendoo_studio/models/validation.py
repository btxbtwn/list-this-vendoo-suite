from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, ValidationError

from vendoo_studio.models.schema import ListingSchema


class ValidationResult(BaseModel):
    valid: bool
    errors: list[dict[str, str]] = Field(default_factory=list)
    warnings: list[dict[str, str]] = Field(default_factory=list)
    info: list[dict[str, str]] = Field(default_factory=list)

    @property
    def can_send(self) -> bool:
        return self.valid and not self.errors


def validate_listing(data: dict, required_photo_count: Optional[int] = None) -> ValidationResult:
    result = ValidationResult(valid=True)

    try:
        ListingSchema.model_validate(data)
    except ValidationError as e:
        result.valid = False
        for err in e.errors():
            result.errors.append({
                "field": ".".join(str(loc) for loc in err["loc"]),
                "message": err["msg"],
            })

    for field in ("title", "description", "price"):
        if not data.get(field):
            result.valid = False
            result.errors.append({
                "field": field,
                "message": f"{field} is required",
            })

    if required_photo_count is not None and required_photo_count == 0:
        result.valid = False
        result.errors.append({
            "field": "photos",
            "message": "At least one product photo is required",
        })

    ebay = data.get("ebay_specifics", {})
    if ebay:
        required_ebay_fields = ["type", "department", "sizeType", "size"]
        for field in required_ebay_fields:
            if not ebay.get(field):
                result.warnings.append({
                    "field": f"ebay_specifics.{field}",
                    "message": f"eBay field '{field}' is recommended for search visibility",
                })

    depop = data.get("depop_specifics", {})
    if depop:
        style_val = depop.get("style", "")
        styles = style_val if isinstance(style_val, list) else [s.strip() for s in str(style_val).split(",") if s.strip()]
        if len(styles) > 3:
            result.warnings.append({
                "field": "depop_specifics.style",
                "message": "Depop allows only 3 style tags",
            })

    return result
