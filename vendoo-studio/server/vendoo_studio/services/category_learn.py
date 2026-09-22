"""Grow category field caches from Vendoo drafts Studio already syncs.

Create/send fills ``category_field_schemas`` and browser probes fill
``category_schemas``. Synced inventory was unused: a pull only stored values.
When Chrome can answer ``category_specifics``, each draft's leaf is fetched
once, stored for Fields/create, and remembered under the general path so the
next generate feeds the model real fields and dropdown options.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import Session

from vendoo_studio.services.category_catalog import remember_schema, schema_covers_platforms
from vendoo_studio.services.category_fields import listing_category_ids, load_fields
from vendoo_studio.services.vendoo_specifics import FieldSpec

log = logging.getLogger("vendoo_studio.category_learn")

__all__ = [
    "category_seed_from_vendoo_item",
    "learn_category_schemas_from_item",
    "specs_as_remember_schema",
]

_MARKETPLACES = ("ebay", "etsy", "poshmark", "mercari", "depop")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _category_path(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [_text(part) for part in value]
        return " > ".join(part for part in parts if part)
    if isinstance(value, dict):
        path = value.get("displayPath") or value.get("path") or value.get("breadcrumb")
        if isinstance(path, list):
            return _category_path(path)
        for key in ("displayName", "name", "label", "value"):
            text = _text(value.get(key))
            if text:
                return text
    return ""


def _leaf_from_section(section: Any) -> dict[str, Any]:
    if not isinstance(section, dict):
        return {}
    overrides = section.get("overrides") if isinstance(section.get("overrides"), dict) else {}
    for source in (overrides, section):
        for key in ("categoryV2", "category"):
            leaf = source.get(key)
            if isinstance(leaf, dict) and (
                _text(leaf.get("id")) or leaf.get("displayPath") or leaf.get("path")
            ):
                return leaf
    return {}


def _path_from_section(section: Any, leaf: dict[str, Any]) -> str:
    path = _category_path(leaf)
    if path:
        return path
    if not isinstance(section, dict):
        return ""
    specifics = section.get("marketplaceSpecifics")
    if isinstance(specifics, dict):
        return _category_path(specifics.get("categoryPath"))
    return ""


def category_seed_from_vendoo_item(item: dict[str, Any] | None) -> dict[str, Any]:
    """Listing-shaped category keys extracted from a raw Vendoo item.

    Enough for ``fetch_listing_specifics`` / ``listing_category_ids`` without a
    Studio revision. Empty when the item carries no leaf ids or breadcrumbs.
    """
    if not isinstance(item, dict):
        return {}
    general = item.get("generalDetails") if isinstance(item.get("generalDetails"), dict) else {}
    general_leaf = general.get("categoryV2") or general.get("category")
    general_leaf = general_leaf if isinstance(general_leaf, dict) else {}
    seed: dict[str, Any] = {}
    general_path = _category_path(general_leaf) or _category_path(general.get("category"))
    if general_path:
        seed["category_path"] = general_path
    general_id = _text(general_leaf.get("id"))
    if general_id:
        seed["category_id"] = general_id

    ids: dict[str, str] = {}
    paths: dict[str, str] = {}
    objects: dict[str, dict[str, Any]] = {}
    listings = item.get("listings") if isinstance(item.get("listings"), dict) else {}
    for marketplace in _MARKETPLACES:
        section = listings.get(marketplace)
        leaf = _leaf_from_section(section)
        path = _path_from_section(section, leaf)
        category_id = _text(leaf.get("id"))
        if category_id:
            ids[marketplace] = category_id
            objects[marketplace] = leaf
        if path:
            paths[marketplace] = path
    if ids:
        seed["marketplace_category_ids"] = ids
    if paths:
        seed["marketplace_categories"] = paths
    if objects:
        seed["marketplace_category_objects"] = objects
    return seed


def specs_as_remember_schema(
    specs_by_marketplace: dict[str, dict[str, FieldSpec]],
    paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    """``remember_schema`` payload from Vendoo ``FieldSpec`` maps."""
    paths = paths if isinstance(paths, dict) else {}
    out: dict[str, Any] = {}
    for marketplace, specs in (specs_by_marketplace or {}).items():
        if not isinstance(specs, dict) or not specs:
            continue
        path = _text(paths.get(marketplace))
        if not path:
            continue
        fields = []
        for spec in specs.values():
            if not isinstance(spec, FieldSpec):
                continue
            options = [
                {"label": label, "value": option_id}
                for option_id, label in (spec.options or {}).items()
                if _text(label)
            ]
            row: dict[str, Any] = {
                "label": spec.display or spec.key,
                "key": spec.key,
                "type": "select" if options else (spec.field_type or "text"),
                "required": bool(spec.required),
                "multiple": bool(spec.multi),
            }
            if options:
                row["options"] = options
                # Vendoo's specifics answer is the full coded list for this leaf.
                row["options_complete"] = True
            fields.append(row)
        if fields:
            out[marketplace] = {
                "category": {"path": path, "status": "cached"},
                "fields": fields,
            }
    return out


async def learn_category_schemas_from_item(
    db: Session,
    item: dict[str, Any] | None,
) -> dict[str, Any]:
    """Fetch missing leaf schemas from a synced Vendoo item and remember them.

    No-ops when there are no leaf ids, everything is already cached for the
    general path, or Chrome cannot answer. Never raises for the sync caller.
    """
    from vendoo_studio.services.vendoo_create import fetch_listing_specifics

    seed = category_seed_from_vendoo_item(item)
    general_path = _text(seed.get("category_path"))
    ids = {
        marketplace: category_id
        for marketplace, category_id in listing_category_ids(seed).items()
        if marketplace != "general" and category_id
    }
    if not ids:
        return {"learned": [], "reason": "no category ids"}

    platforms = list(ids)
    if (
        general_path
        and all(load_fields(marketplace, category_id) for marketplace, category_id in ids.items())
        and schema_covers_platforms(db, general_path, platforms)
    ):
        return {"learned": [], "reason": "already cached", "general_path": general_path}

    try:
        specs = await fetch_listing_specifics(SimpleNamespace(id=None), seed)
    except Exception:  # noqa: BLE001 - sync must not fail over schema learning
        log.info("category schema learn fetch failed", exc_info=True)
        return {"learned": [], "reason": "fetch failed", "general_path": general_path}

    learned = sorted(str(marketplace) for marketplace, fields in (specs or {}).items() if fields)
    if not specs:
        return {"learned": [], "reason": "empty", "general_path": general_path}

    if general_path:
        schema = specs_as_remember_schema(specs, seed.get("marketplace_categories"))
        if schema:
            try:
                remember_schema(db, general_path, schema)
            except Exception:  # noqa: BLE001 - leaf cache still grew via save_fields
                log.info("remember_schema after sync failed path=%s", general_path, exc_info=True)

    log.info(
        "learned category schemas from sync path=%s marketplaces=%s",
        general_path or "?",
        ",".join(learned),
    )
    return {"learned": learned, "general_path": general_path, "reason": "ok"}
