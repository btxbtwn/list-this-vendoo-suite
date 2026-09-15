from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.models.catalog import CategoryNode, CategorySchema, CategoryTree, CategoryTreeNode
from vendoo_studio.services.category_tree import MARKETPLACES, start_sync, syncing

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("/categories")
def categories(marketplace: str = "general", db: Session = Depends(get_db)):
    tree = db.get(CategoryTree, marketplace)
    if tree:
        rows = db.query(CategoryTreeNode).filter_by(marketplace=marketplace).order_by(CategoryTreeNode.path).all()
        return {"coverage": "tree", "complete": tree.status == "complete", "nodes": [{
            "id": row.category_id, "parent_id": row.parent_id, "path": row.path,
            "label": row.label, "is_leaf": row.is_leaf, "has_children": row.has_children,
        } for row in rows]}
    rows = db.query(CategoryNode).filter_by(marketplace=marketplace).order_by(CategoryNode.path).all()
    return {"coverage": "observed", "complete": False, "nodes": [{
        "path": row.path, "parent_path": row.parent_path, "label": row.label,
        "observed_at": row.observed_at.isoformat(),
    } for row in rows]}


@router.get("/sync")
def sync_status(db: Session = Depends(get_db)):
    result = {}
    for marketplace in MARKETPLACES:
        tree = db.get(CategoryTree, marketplace)
        query = db.query(CategoryTreeNode).filter_by(marketplace=marketplace)
        status = tree.status if tree else "pending"
        if status == "running" and not syncing():
            status = "paused"
        result[marketplace] = {"status": status,
            "nodes": query.count(), "pending_branches": query.filter_by(children_loaded=False).count(),
            "error": tree.error if tree else None}
    return {"running": syncing(), "complete": all(row["status"] == "complete" for row in result.values()),
            "marketplaces": result}


@router.post("/sync")
async def sync_categories(db: Session = Depends(get_db)):
    from vendoo_studio.repositories.queries import JobRepo
    from vendoo_studio.routes.extension import extension_manager
    if JobRepo(db).get_active():
        raise HTTPException(409, "Wait for the current listing job before extracting categories")
    if not extension_manager.connected:
        raise HTTPException(409, "Connect Chrome before extracting categories")
    start_sync()
    return {"started": True}


@router.get("/schema")
def schema(category_path: str, db: Session = Depends(get_db)):
    rows = db.query(CategorySchema).filter_by(general_path=category_path).all()
    return {row.marketplace: {"category_path": row.category_path, "fields": row.fields,
                             "observed_at": row.observed_at.isoformat()} for row in rows}
