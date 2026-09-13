from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any

from vendoo_studio.repositories.queries import _normalize_label
from vendoo_studio.services.registry import label_to_json_key

log = logging.getLogger("vendoo_studio.listing_patch")

_SPECIAL_LABELS = {
    "category_path": "Category",
    "department": "Department",
    "styleTags": "Style tags",
    "primaryStoreCategory": "Store category",
    "secondaryStoreCategory": "Secondary store category",
    "primaryColor": "Primary color",
    "secondaryColor": "Secondary color",
}


def extract_json_patch(text: str) -> list[dict] | None:
    """Find a JSON Patch array in raw, fenced, or mixed assistant text."""
    if not text or text.lstrip().lower().startswith("error:"):
        return None

    candidates: list[str] = []
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        candidates.append(fenced.group(1).strip())
    stripped = text.strip()
    if stripped:
        candidates.append(stripped)
    for match in re.finditer(r"\[[\s\S]*\]", text):
        candidates.append(match.group().strip())

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if _is_patch(parsed):
            return parsed
    return None


def summarize_json_patch(operations: list[dict]) -> str:
    lines: list[str] = []
    for op in operations:
        if not isinstance(op, dict):
            continue
        label = _path_label(str(op.get("path") or ""))
        op_type = op.get("op")
        if op_type == "remove":
            lines.append(f"Removed {label}")
            continue
        if op_type not in {"replace", "add"}:
            continue
        lines.append(f"{label}: {_display_value(op.get('value'))}")
    if not lines:
        return "Saved those changes to the listing."
    if len(lines) == 1:
        return f"Updated the listing — {lines[0]}."
    return "Updated the listing:\n" + "\n".join(f"- {line}" for line in lines)


def apply_json_patch(document: dict, operations: list[dict]) -> dict:
    """Apply a JSON Patch array onto a listing dict, including list indexes."""
    updated = copy.deepcopy(document)
    for op in operations:
        if not isinstance(op, dict):
            continue
        op_type = op.get("op")
        path = op.get("path") or ""
        if not path.startswith("/"):
            continue
        tokens = [_unescape_pointer(token) for token in path.lstrip("/").split("/") if token != ""]
        if not tokens:
            continue
        try:
            if op_type in {"replace", "add"}:
                _set_path(updated, tokens, op.get("value"))
            elif op_type == "remove":
                _remove_path(updated, tokens)
        except Exception as exc:
            log.warning("skipped json patch op %s: %s", op, exc)
            continue
    return updated


def _is_patch(parsed: Any) -> bool:
    return bool(
        isinstance(parsed, list)
        and parsed
        and all(isinstance(op, dict) and op.get("op") for op in parsed)
    )


def _unescape_pointer(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _path_label(path: str) -> str:
    parts = [part for part in path.strip("/").split("/") if part and part != "-" and not part.isdigit()]
    if not parts:
        return "Field"
    prefix = ""
    first = parts[0]
    if first.endswith("_specifics"):
        market = first[: -len("_specifics")]
        prefix = "eBay" if market == "ebay" else market.title()
        parts = parts[1:]
    key = parts[-1] if parts else first
    label = _SPECIAL_LABELS.get(key) or _human_key(key)
    return f"{prefix} {label}".strip() if prefix else label


def _human_key(token: str) -> str:
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", token.replace("_", " "))
    return spaced.replace("-", " ").strip().title()


def _display_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _resolve_key(container: Any, token: str) -> Any:
    if isinstance(container, list):
        if token == "-":
            return "-"
        if token.isdigit():
            return int(token)
        raise TypeError(f"Cannot use {token!r} as a list index")
    if not isinstance(container, dict):
        raise TypeError(f"Cannot walk into {type(container).__name__}")
    if token in container:
        return token
    token_norm = _normalize_label(token)
    for key in container:
        if not isinstance(key, str):
            continue
        if _normalize_label(key) == token_norm:
            return key
        if label_to_json_key(key) == token:
            return key
    return token


def _child_container(want_list: bool) -> list | dict:
    return [] if want_list else {}


def _wants_list(token: str) -> bool:
    return token == "-" or token.isdigit()


def _set_path(root: dict, tokens: list[str], value: Any) -> None:
    current: Any = root
    for i, token in enumerate(tokens[:-1]):
        key = _resolve_key(current, token)
        want_list = _wants_list(tokens[i + 1])
        if isinstance(current, list):
            if not isinstance(key, int) or key < 0:
                raise TypeError("Invalid list index in path")
            while len(current) <= key:
                current.append(_child_container(want_list))
            child = current[key]
            if want_list and not isinstance(child, list):
                current[key] = []
            elif not want_list and not isinstance(child, dict):
                current[key] = {}
            current = current[key]
            continue
        existing = current.get(key)
        if isinstance(existing, list):
            if not want_list:
                raise TypeError("Cannot walk a non-index into a list")
            current = existing
            continue
        if want_list and not isinstance(existing, list):
            current[key] = []
        elif not want_list and not isinstance(existing, dict):
            current[key] = {}
        current = current[key]

    last = _resolve_key(current, tokens[-1])
    if isinstance(current, list):
        if last == "-":
            current.append(value)
            return
        if not isinstance(last, int) or last < 0:
            raise TypeError("Invalid list index in path")
        while len(current) < last:
            current.append(None)
        if last == len(current):
            current.append(value)
        else:
            current[last] = value
        return
    current[last] = value


def _remove_path(root: dict, tokens: list[str]) -> None:
    current: Any = root
    for token in tokens[:-1]:
        key = _resolve_key(current, token)
        current = current[key]
    last = _resolve_key(current, tokens[-1])
    if isinstance(current, list) and isinstance(last, int) and 0 <= last < len(current):
        del current[last]
        return
    if isinstance(current, dict) and last in current:
        del current[last]
