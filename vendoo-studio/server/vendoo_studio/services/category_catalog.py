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


def schema_context(db: Session, path: str) -> str:
    rows = db.query(CategorySchema).filter_by(general_path=path).all()
    if not rows:
        return ""
    return "\n\n--- Observed category fields ---\n" + json.dumps({row.marketplace: {
        "category_path": row.category_path, "fields": row.fields,
    } for row in rows}, ensure_ascii=False) + (
        "\nResolve every applicable field using photo evidence or seller answers. "
        "Use exact allowed option labels. Ask for unknown facts; never invent them. "
        "These are observed fields, not proof that all conditional fields have been exposed.\n"
    )
