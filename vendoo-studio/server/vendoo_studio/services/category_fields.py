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

__all__ = ["load_fields", "save_fields", "cached_marketplaces", "load_rows",
           "listing_category_ids"]


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


def listing_category_ids(listing: dict[str, Any]) -> dict[str, str]:
    """``{marketplace: leaf id}`` for a listing, without going near the network.

    Prefers ids already resolved onto the listing; otherwise looks the chosen
    breadcrumb up in the seeded tree. Categories only live there once they have
    been discovered, so an unknown path is simply absent rather than guessed.
    """
    if not isinstance(listing, dict):
        return {}
    out: dict[str, str] = {}
    known = listing.get("marketplace_category_ids")
    if isinstance(known, dict):
        for marketplace, value in known.items():
            text = str(value or "").strip()
            if text:
                out[str(marketplace).strip().lower()] = text
    paths = listing.get("marketplace_categories")
    if isinstance(paths, dict):
        from vendoo_studio.services.vendoo_create import tree_leaf

        for marketplace, path in paths.items():
            key = str(marketplace).strip().lower()
            if key in out or not str(path or "").strip():
                continue
            leaf = tree_leaf(key, str(path))
            if leaf and leaf.get("id"):
                out[key] = str(leaf["id"])
    return out
