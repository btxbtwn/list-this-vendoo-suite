from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.models.catalog import CategoryNode, CategorySchema

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("/categories")
def categories(marketplace: str = "general", db: Session = Depends(get_db)):
    rows = db.query(CategoryNode).filter_by(marketplace=marketplace).order_by(CategoryNode.path).all()
    return {"coverage": "observed", "complete": False, "nodes": [{
        "path": row.path, "parent_path": row.parent_path, "label": row.label,
        "observed_at": row.observed_at.isoformat(),
    } for row in rows]}


@router.get("/schema")
def schema(category_path: str, db: Session = Depends(get_db)):
    rows = db.query(CategorySchema).filter_by(general_path=category_path).all()
    return {row.marketplace: {"category_path": row.category_path, "fields": row.fields,
                             "observed_at": row.observed_at.isoformat()} for row in rows}
