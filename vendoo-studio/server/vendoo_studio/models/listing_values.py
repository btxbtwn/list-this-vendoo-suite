"""Shared value coercion, dropdown option matching, and the validation result type."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from vendoo_studio.config import skills_dir
from vendoo_studio.models.mercari_shipping import DEFAULT_SHIPPING_LABEL

DNA_VALUE = "Does Not Apply"


class ValidationResult(BaseModel):
    valid: bool
    errors: list[dict[str, str]] = Field(default_factory=list)
    warnings: list[dict[str, str]] = Field(default_factory=list)
    info: list[dict[str, str]] = Field(default_factory=list)

    @property
    def can_send(self) -> bool:
        return self.valid and not self.errors


def add_issue(result: ValidationResult, field: str, message: str, *, warning: bool = False) -> None:
    item = {"field": field, "message": message}
    bucket = result.warnings if warning else result.errors
    if any(existing["field"] == field and existing["message"] == message for existing in bucket):
        return
    if not warning and any(existing["field"] == field and existing["message"] == message for existing in result.errors):
        return
    bucket.append(item)
    if not warning:
        result.valid = False


def as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    text = str(value).strip()
    return [text] if text else []


def text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def as_mapping(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


@lru_cache(maxsize=1)
def dropdown_options() -> dict[str, Any]:
    path = skills_dir() / "list-this" / "references" / "vendoo-dropdown-options.json"
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


# USPS Ground Advantage tier shown on this seller's Mercari form. The scraped
# dropdown JSON only recorded "disabled" because Mercari was disconnected.
_MERCARI_SHIPPING_LABELS = (DEFAULT_SHIPPING_LABEL,)


@lru_cache(maxsize=1)
def marketplace_dropdown_forms() -> dict[str, dict[str, list[str]]]:
    """Static Vendoo option lists for the Forms editor, keyed by marketplace then field."""
    raw = dropdown_options().get("forms") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, list[str]]] = {}
    for marketplace, fields in raw.items():
        if not isinstance(fields, dict):
            continue
        cleaned: dict[str, list[str]] = {}
        for field, options in fields.items():
            labels = [
                str(option).strip()
                for option in (options if isinstance(options, list) else [])
                if str(option).strip() and str(option).strip() != "----"
            ]
            if labels:
                cleaned[str(field)] = labels
        if cleaned:
            out[str(marketplace)] = cleaned
    mercari = out.setdefault("mercari", {})
    mercari["shippingLabel"] = list(_MERCARI_SHIPPING_LABELS)
    ebay = out.setdefault("ebay", {})
    # Scrape used display labels; createItem stores FixedPriceItem.
    ebay["pricingFormat"] = ["Fixed Price", "Auction Style", "FixedPriceItem"]
    return out


def dedupe_schema_errors(errors: Iterable[dict[str, str]]) -> list[dict[str, str]]:
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


def collapse_option(text: str) -> str:
    collapsed = re.sub(r"[\s\-–—/:]+", " ", str(text or "").strip().lower())
    return collapsed.strip()


def normalized_option_key(text: str) -> str:
    return collapse_option(str(text or "").split("(", 1)[0])


def canonical_option(value: str, allowed: Iterable[str]) -> str | None:
    needle = str(value or "").strip()
    if not needle:
        return None
    needle_full = collapse_option(needle)
    needle_key = normalized_option_key(needle)
    ranked = sorted(
        (
            str(option).strip()
            for option in allowed
            if str(option).strip() and str(option).strip() != "----"
        ),
        key=lambda option: len(normalized_option_key(option)),
        reverse=True,
    )
    for option in ranked:
        option_full = collapse_option(option)
        option_key = normalized_option_key(option)
        if needle_full == option_full or needle_key == option_key:
            return option
        if option_key and (
            needle_key.startswith(f"{option_key} ")
            or needle_full.startswith(f"{option_key} ")
            or needle_full.startswith(f"{option_full} ")
        ):
            return option
    return None


def allowed_match(value: str, allowed: Iterable[str]) -> bool:
    return canonical_option(value, allowed) is not None


def evidence_unknown(description: str, *needles: str) -> bool:
    lower = description.lower()
    return any(needle in lower for needle in needles)

def dropdown_field_options(marketplace: str, *field_names: str) -> list[str]:
    """Known Vendoo dropdown labels for a marketplace field (first matching name wins)."""
    forms = marketplace_dropdown_forms().get(str(marketplace or "").casefold()) or {}
    if not isinstance(forms, dict):
        return []
    for name in field_names:
        labels = forms.get(name)
        if isinstance(labels, list) and labels:
            return [str(label) for label in labels if str(label).strip()]
        needle_key = collapse_option(name)
        for key, labels in forms.items():
            if collapse_option(key) == needle_key and isinstance(labels, list) and labels:
                return [str(label) for label in labels if str(label).strip()]
    return []


def infer_known_option(
    hay: str,
    options: Iterable[str],
    *,
    cues: dict[str, tuple[str, ...]] | None = None,
    fallback: str | None = None,
    exclude: Iterable[str] | None = None,
) -> str | None:
    """Pick the best known dropdown option from listing text, or ``fallback``."""
    picked = infer_known_options(
        hay,
        options,
        cues=cues,
        fallbacks=(fallback,) if fallback else (),
        limit=1,
        exclude=exclude,
    )
    return picked[0] if picked else None


def infer_known_options(
    hay: str,
    options: Iterable[str],
    *,
    cues: dict[str, tuple[str, ...]] | None = None,
    fallbacks: Iterable[str] = (),
    limit: int = 3,
    exclude: Iterable[str] | None = None,
) -> list[str]:
    """Score known dropdown options against listing text; pad with fallbacks to ``limit``."""
    limit = max(0, int(limit))
    if limit == 0:
        return []
    blocked = {str(item) for item in (exclude or ()) if item}
    labels = [
        str(option).strip()
        for option in options
        if str(option).strip() and str(option).strip() != "----" and str(option).strip() not in blocked
    ]
    if not labels:
        out: list[str] = []
        for fallback in fallbacks:
            text_fb = str(fallback or "").strip()
            if text_fb and text_fb not in out and text_fb not in blocked:
                out.append(text_fb)
            if len(out) >= limit:
                break
        return out[:limit]

    text_hay = str(hay or "")
    scores: dict[str, int] = {label: 0 for label in labels}
    for label in labels:
        if re.search(rf"\b{re.escape(label)}\b", text_hay, flags=re.I):
            scores[label] += 3
        collapsed = collapse_option(label)
        if collapsed and re.search(rf"\b{re.escape(collapsed)}\b", collapse_option(text_hay), flags=re.I):
            scores[label] += 2

    for label, patterns in (cues or {}).items():
        if label not in scores:
            hit = canonical_option(label, labels)
            if not hit or hit not in scores:
                continue
            target = hit
        else:
            target = label
        for pattern in patterns:
            if re.search(pattern, text_hay, flags=re.I):
                scores[target] += 1

    ranked = sorted(
        (name for name, score in scores.items() if score > 0),
        key=lambda name: (-scores[name], name),
    )
    picked: list[str] = []
    for name in ranked:
        if name not in picked:
            picked.append(name)
        if len(picked) >= limit:
            return picked[:limit]
    for fallback in fallbacks:
        text_fb = str(fallback or "").strip()
        if not text_fb or text_fb in blocked:
            continue
        hit = canonical_option(text_fb, labels) or text_fb
        if hit not in picked:
            picked.append(hit)
        if len(picked) >= limit:
            break
    return picked[:limit]
