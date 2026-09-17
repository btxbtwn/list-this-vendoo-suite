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
