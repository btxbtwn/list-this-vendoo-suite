"""Observed category trees and reusable field definitions, without listing values."""
import json

from sqlalchemy.orm import Session

from vendoo_studio.models.catalog import CategoryNode, CategorySchema
from vendoo_studio.models.conversation import utcnow


def remember_path(db: Session, marketplace: str, path: str) -> None:
    parts = [part.strip() for part in str(path or "").split(">") if part.strip()]
    for index, label in enumerate(parts):
        branch = " > ".join(parts[:index + 1])
        node = db.query(CategoryNode).filter_by(marketplace=marketplace, path=branch).first()
        if node is None:
            node = CategoryNode(marketplace=marketplace, path=branch,
                                parent_path=" > ".join(parts[:index]), label=label)
            db.add(node)
        node.observed_at = utcnow()
        db.flush()


def remember_schema(db: Session, general_path: str, schema: dict) -> None:
    if not general_path:
        return
    remember_path(db, "general", general_path)
    for marketplace, section in schema.items():
        if not isinstance(section, dict) or section.get("error") or not section.get("fields"):
            continue
        category = section.get("category") or {}
        path = str(category.get("path") or "")
        if not path:
            continue
        remember_path(db, marketplace, path)
        # Never cache values, errors or selectors from a seller's particular item.
        fields = [{key: field[key] for key in (
            "label", "key", "type", "required", "options", "options_complete", "multiple",
            "min", "max", "max_length", "pattern",
        ) if key in field} for field in section["fields"] if isinstance(field, dict)]
        row = db.query(CategorySchema).filter_by(general_path=general_path, marketplace=marketplace).first()
        if row is None:
            row = CategorySchema(general_path=general_path, marketplace=marketplace)
            db.add(row)
        row.category_path = path
        row.fields = fields
        row.observed_at = utcnow()
    db.commit()
    try:
        from vendoo_studio.services.catalog_index import mark_catalog_index_stale
        mark_catalog_index_stale()
    except Exception:
        pass


def _schema_rows_by_marketplace(db: Session, general_path: str) -> dict[str, CategorySchema]:
    path = str(general_path or "").strip()
    if not path:
        return {}
    return {
        str(row.marketplace or "").strip().lower(): row
        for row in db.query(CategorySchema).filter_by(general_path=path).all()
    }


def schema_covers_platforms(db: Session, general_path: str, platforms: list[str]) -> bool:
    """True when every fillable marketplace already has a cached field schema for this category."""
    path = str(general_path or "").strip()
    wanted = [str(item or "").strip().lower() for item in (platforms or []) if str(item or "").strip()]
    if not path or not wanted:
        return False
    rows = _schema_rows_by_marketplace(db, path)
    for marketplace in wanted:
        row = rows.get(marketplace)
        if row is None:
            return False
        if not str(row.category_path or "").strip():
            return False
        fields = row.fields if isinstance(row.fields, list) else []
        if not fields:
            return False
    return True


def cached_schema_payload(db: Session, general_path: str, platforms: list[str]) -> dict | None:
    """Probe-shaped schema from category_schemas, or None when any marketplace is incomplete."""
    path = str(general_path or "").strip()
    wanted = [str(item or "").strip().lower() for item in (platforms or []) if str(item or "").strip()]
    if not path or not wanted:
        return None
    rows = _schema_rows_by_marketplace(db, path)
    payload: dict = {}
    for marketplace in wanted:
        row = rows.get(marketplace)
        if row is None:
            return None
        category_path = str(row.category_path or "").strip()
        fields = row.fields if isinstance(row.fields, list) else []
        if not category_path or not fields:
            return None
        payload[marketplace] = {
            "category": {"path": category_path, "status": "cached"},
            "fields": fields,
        }
    return payload


def schema_context(db: Session, path: str) -> str:
    rows = list(_schema_rows_by_marketplace(db, path).values())
    if not rows and path:
        try:
            from vendoo_studio.services.catalog_index import search_catalog
            hits = search_catalog(db, path, kind="schema", top_k=6)
            seen = set()
            matched = []
            for hit in hits:
                key = (hit.get("marketplace"), hit.get("general_path") or hit.get("path"))
                if key in seen:
                    continue
                seen.add(key)
                row = db.query(CategorySchema).filter_by(
                    general_path=str(hit.get("general_path") or ""),
                    marketplace=str(hit.get("marketplace") or ""),
                ).first()
                if row:
                    matched.append(row)
            rows = matched
        except Exception:
            rows = []
    if not rows:
        return ""
    return "\n\n--- Observed category fields ---\n" + json.dumps({row.marketplace: {
        "category_path": row.category_path, "fields": row.fields,
    } for row in rows}, ensure_ascii=False) + (
        "\nResolve every applicable field using photo evidence and initial seller notes. "
        "Use exact allowed option labels. Infer supportable facts; leave unsupported facts empty and note them — never ask. "
        "Fill every applicable field in the listing JSON now (root fields or marketplace *_specifics). "
        "These are observed fields, not proof that all conditional fields have been exposed.\n"
    )
