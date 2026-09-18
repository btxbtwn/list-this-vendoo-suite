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


@router.get("/search")
def search(
    q: str,
    marketplace: str | None = None,
    kind: str = "all",
    top_k: int = 15,
    db: Session = Depends(get_db),
):
    from vendoo_studio.services.catalog_index import search_catalog

    query = str(q or "").strip()
    if not query:
        raise HTTPException(400, "q is required")
    if kind not in {"category", "schema", "option", "skill", "fill", "all"}:
        raise HTTPException(400, "kind must be category, schema, option, skill, fill, or all")
    top_k = max(1, min(int(top_k or 15), 50))
    try:
        hits = search_catalog(db, query, marketplace=marketplace or None, kind=kind, top_k=top_k)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"query": query, "kind": kind, "marketplace": marketplace, "results": hits}


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


@router.get("/fields")
def fields(marketplace: str, category_id: str):
    """Vendoo's field list for one marketplace category.

    Every field that category renders, including the optional ones it unlocks,
    with ``required``, ``multi`` and the coded options each accepts. Served from
    the cache the create path fills, so this needs no Chrome session.
    """
    from vendoo_studio.services.category_fields import load_rows

    rows = load_rows(marketplace, category_id)
    if rows is None:
        raise HTTPException(
            404,
            f"No cached field schema for {marketplace} category {category_id}. "
            "Create or refresh a listing in that category to fetch it.",
        )
    return {
        "marketplace": marketplace,
        "category_id": category_id,
        "required": [row["key"] for row in rows if row.get("required")],
        "fields": rows,
    }


@router.get("/schema")
def schema(category_path: str, db: Session = Depends(get_db)):
    rows = db.query(CategorySchema).filter_by(general_path=category_path).all()
    return {row.marketplace: {"category_path": row.category_path, "fields": row.fields,
                             "observed_at": row.observed_at.isoformat()} for row in rows}
