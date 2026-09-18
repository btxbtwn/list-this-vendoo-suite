"""Cache of Vendoo's per-category field schemas.

``/api/category/specifics`` needs the extension and a live Vendoo session, and
the answer for a given leaf only changes when Vendoo changes its taxonomy. So
every fetch is stored keyed by ``(marketplace, category_id)``, which lets the
Fields UI and listing generation read the full field list — including the
optional fields a category unlocks — without going through Chrome.

``vendoo_specifics`` stays pure; this is the only part that touches the store.
"""
from __future__ import annotations

import logging
from typing import Any

from vendoo_studio.database import SessionLocal
from vendoo_studio.models.catalog import CategoryFieldSchema
from vendoo_studio.services.vendoo_specifics import (
    FieldSpec,
    specs_from_rows,
    specs_to_rows,
)

log = logging.getLogger("vendoo_studio.category_fields")

__all__ = ["load_fields", "save_fields", "cached_marketplaces", "load_rows"]


def load_rows(marketplace: str, category_id: str) -> list[dict[str, Any]] | None:
    """The stored rows for one leaf, or None when nothing is cached."""
    if not marketplace or not category_id:
        return None
    with SessionLocal() as db:
        row = (
            db.query(CategoryFieldSchema)
            .filter_by(marketplace=str(marketplace), category_id=str(category_id))
            .one_or_none()
        )
        return list(row.fields or []) if row else None


def load_fields(marketplace: str, category_id: str) -> dict[str, FieldSpec] | None:
    rows = load_rows(marketplace, category_id)
    if rows is None:
        return None
    specs = specs_from_rows(rows)
    return specs or None


def save_fields(marketplace: str, category_id: str, specs: dict[str, FieldSpec]) -> None:
    """Store one leaf's schema, replacing whatever was there."""
    if not marketplace or not category_id or not specs:
        return
    rows = specs_to_rows(specs)
    with SessionLocal() as db:
        existing = (
            db.query(CategoryFieldSchema)
            .filter_by(marketplace=str(marketplace), category_id=str(category_id))
            .one_or_none()
        )
        if existing:
            existing.fields = rows
        else:
            db.add(CategoryFieldSchema(
                marketplace=str(marketplace), category_id=str(category_id), fields=rows
            ))
        db.commit()


def cached_marketplaces(category_ids: dict[str, str]) -> dict[str, dict[str, FieldSpec]]:
    """Cached schemas for a ``{marketplace: category_id}`` map."""
    out: dict[str, dict[str, FieldSpec]] = {}
    for marketplace, category_id in (category_ids or {}).items():
        specs = load_fields(marketplace, category_id)
        if specs:
            out[marketplace] = specs
    return out
