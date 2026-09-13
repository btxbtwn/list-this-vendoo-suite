from __future__ import annotations

from typing import Literal

from vendoo_studio.services.user_settings import read_settings, update_settings

Scope = Literal["always", "listing"]


def normalize_marketplace(value: str) -> str:
    return str(value or "").strip().lower()


def normalize_field_name(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _entry(marketplace: str, field: str, label: str | None = None) -> dict[str, str]:
    market = normalize_marketplace(marketplace)
    name = normalize_field_name(field)
    shown = " ".join(str(label or "").split()) or field.strip() or name
    return {"marketplace": market, "field": name, "label": shown}


def _clean_entries(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    seen: set[tuple[str, str]] = set()
    entries: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        entry = _entry(str(item.get("marketplace") or ""), str(item.get("field") or ""), item.get("label"))
        if not entry["marketplace"] or not entry["field"]:
            continue
        key = (entry["marketplace"], entry["field"])
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
    return entries


def _from_settings(settings: dict) -> dict:
    stored = settings.get("hidden_fields")
    if not isinstance(stored, dict):
        stored = {}
    listings = stored.get("listings")
    cleaned_listings = {
        str(conversation_id): _clean_entries(entries)
        for conversation_id, entries in (listings.items() if isinstance(listings, dict) else [])
        if str(conversation_id).strip()
    }
    return {
        "always": _clean_entries(stored.get("always")),
        "listings": {key: value for key, value in cleaned_listings.items() if value},
    }


def _store(settings: dict, payload: dict) -> None:
    settings["hidden_fields"] = {
        "always": payload["always"],
        "listings": payload["listings"],
    }


def _same(item: dict[str, str], entry: dict[str, str]) -> bool:
    return item["marketplace"] == entry["marketplace"] and item["field"] == entry["field"]


def _without(entries: list[dict[str, str]], entry: dict[str, str]) -> list[dict[str, str]]:
    return [item for item in entries if not _same(item, entry)]


def hidden_fields(conversation_id: str | None = None) -> dict[str, list[dict[str, str]]]:
    stored = _from_settings(read_settings())
    listing_id = str(conversation_id or "").strip()
    return {
        "always": stored["always"],
        "listing": stored["listings"].get(listing_id, []) if listing_id else [],
    }


def hide_field(
    marketplace: str,
    field: str,
    scope: Scope,
    conversation_id: str | None = None,
    label: str | None = None,
) -> dict[str, list[dict[str, str]]]:
    entry = _entry(marketplace, field, label)
    if not entry["marketplace"] or not entry["field"]:
        raise ValueError("marketplace and field are required")
    if scope not in {"always", "listing"}:
        raise ValueError("scope must be always or listing")
    listing_id = str(conversation_id or "").strip()
    if scope == "listing" and not listing_id:
        raise ValueError("conversation_id is required to hide a field on one listing")

    result = {"always": [], "listing": []}

    def mutator(settings: dict) -> None:
        stored = _from_settings(settings)
        if scope == "always":
            always = _without(stored["always"], entry)
            always.append(entry)
            listings = {
                key: _without(value, entry)
                for key, value in stored["listings"].items()
            }
            stored["always"] = always
            stored["listings"] = {key: value for key, value in listings.items() if value}
        elif any(_same(item, entry) for item in stored["always"]):
            pass
        else:
            current = _without(stored["listings"].get(listing_id, []), entry)
            current.append(entry)
            stored["listings"][listing_id] = current
        _store(settings, stored)
        result["always"] = stored["always"]
        result["listing"] = stored["listings"].get(listing_id, []) if listing_id else []

    update_settings(mutator)
    return result


def restore_field(
    marketplace: str,
    field: str,
    scope: Scope,
    conversation_id: str | None = None,
) -> dict[str, list[dict[str, str]]]:
    entry = _entry(marketplace, field)
    if not entry["marketplace"] or not entry["field"]:
        raise ValueError("marketplace and field are required")
    if scope not in {"always", "listing"}:
        raise ValueError("scope must be always or listing")
    listing_id = str(conversation_id or "").strip()
    if scope == "listing" and not listing_id:
        raise ValueError("conversation_id is required to restore a field on one listing")

    result = {"always": [], "listing": []}

    def mutator(settings: dict) -> None:
        stored = _from_settings(settings)
        if scope == "always":
            stored["always"] = _without(stored["always"], entry)
        else:
            remaining = _without(stored["listings"].get(listing_id, []), entry)
            if remaining:
                stored["listings"][listing_id] = remaining
            else:
                stored["listings"].pop(listing_id, None)
        _store(settings, stored)
        result["always"] = stored["always"]
        result["listing"] = stored["listings"].get(listing_id, []) if listing_id else []

    update_settings(mutator)
    return result


def restore_all_fields(conversation_id: str | None = None) -> dict[str, list[dict[str, str]]]:
    """Clear always-hidden fields and this listing's hidden fields."""
    listing_id = str(conversation_id or "").strip()
    result = {"always": [], "listing": []}

    def mutator(settings: dict) -> None:
        stored = _from_settings(settings)
        stored["always"] = []
        if listing_id:
            stored["listings"].pop(listing_id, None)
        _store(settings, stored)
        result["always"] = []
        result["listing"] = []

    update_settings(mutator)
    return result


def restore_matching_fields(
    matches: list[tuple[str, str]],
    conversation_id: str | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Restore specific marketplace/field pairs from always and listing scopes."""
    wanted = {
        (normalize_marketplace(market), normalize_field_name(field))
        for market, field in matches
        if str(market or "").strip() and str(field or "").strip()
    }
    listing_id = str(conversation_id or "").strip()
    result = {"always": [], "listing": []}

    def mutator(settings: dict) -> None:
        stored = _from_settings(settings)
        stored["always"] = [
            item for item in stored["always"] if (item["marketplace"], item["field"]) not in wanted
        ]
        if listing_id and listing_id in stored["listings"]:
            remaining = [
                item
                for item in stored["listings"][listing_id]
                if (item["marketplace"], item["field"]) not in wanted
            ]
            if remaining:
                stored["listings"][listing_id] = remaining
            else:
                stored["listings"].pop(listing_id, None)
        _store(settings, stored)
        result["always"] = stored["always"]
        result["listing"] = stored["listings"].get(listing_id, []) if listing_id else []

    update_settings(mutator)
    return result
