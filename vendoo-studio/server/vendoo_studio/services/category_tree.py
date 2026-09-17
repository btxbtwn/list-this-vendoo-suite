"""Checkpointed extraction of the six category trees used by Vendoo's forms."""
import asyncio
import uuid

from vendoo_studio.database import SessionLocal
from vendoo_studio.models.catalog import CategoryTree, CategoryTreeNode

MARKETPLACES = ("general", "ebay", "poshmark", "mercari", "depop", "etsy")
_task: asyncio.Task | None = None


def syncing() -> bool:
    return _task is not None and not _task.done()


async def read_children(marketplace: str, parent_id: str = "__root") -> dict:
    from vendoo_studio.routes.extension import extension_manager
    request_id = "tree:" + uuid.uuid4().hex
    future = extension_manager.register_wait(request_id)
    try:
        sent = await extension_manager.send_message({"type": "catalog.read_children", "payload": {
            "request_id": request_id, "marketplace": marketplace, "parent_id": parent_id,
        }})
        if not sent:
            raise RuntimeError("Connect Chrome before extracting categories")
        result = await asyncio.wait_for(future, timeout=60)
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "Category extraction failed")
        return result
    finally:
        extension_manager.cancel_wait(request_id)


def store_children(db, marketplace: str, parent_id: str, result: dict) -> None:
    tree = db.get(CategoryTree, marketplace)
    parent = None if parent_id == "__root" else db.get(CategoryTreeNode, (marketplace, parent_id))
    records = result.get("nodes")
    if not isinstance(records, list) or (not records and (parent is None or parent.has_children)):
        raise ValueError(f"{marketplace}: expected category children for {parent_id}")
    seen = set()
    for record in records:
        category_id = str(record["id"])
        parts = record["path"]
        if not category_id or category_id == parent_id or category_id in seen or not parts:
            raise ValueError("Invalid or duplicate category in tree response")
        seen.add(category_id)
        path = " > ".join(parts)
        if parent and not path.startswith(parent.path + " > "):
            raise ValueError("Category child is outside its parent path")
        node = db.get(CategoryTreeNode, (marketplace, category_id))
        if node and node.parent_id != parent_id:
            raise ValueError("Category occurs under multiple parents")
        if node is None:
            node = CategoryTreeNode(marketplace=marketplace, category_id=category_id, parent_id=parent_id)
            db.add(node)
        node.path, node.label = path, record["label"]
        node.is_leaf, node.has_children = record["is_leaf"], record["has_children"]
        if not node.has_children:
            node.children_loaded = True
    if parent:
        parent.children_loaded = True
    else:
        tree.roots_loaded = True
    tree.source = result.get("source")
    db.commit()


async def extract_trees() -> None:
    for marketplace in MARKETPLACES:
        with SessionLocal() as db:
            tree = db.get(CategoryTree, marketplace)
            if tree is None:
                tree = CategoryTree(marketplace=marketplace)
                db.add(tree)
                db.commit()
            if tree.status == "complete":
                continue
            tree.status, tree.error = "running", None
            db.commit()
            try:
                if not tree.roots_loaded:
                    store_children(db, marketplace, "__root", await read_children(marketplace))
                while True:
                    pending = db.query(CategoryTreeNode).filter_by(
                        marketplace=marketplace, children_loaded=False).limit(4).all()
                    if not pending:
                        break
                    results = await asyncio.gather(*(read_children(marketplace, node.category_id)
                                                     for node in pending), return_exceptions=True)
                    failures = []
                    for node, result in zip(pending, results, strict=True):
                        if isinstance(result, BaseException):
                            failures.append(str(result))
                        else:
                            store_children(db, marketplace, node.category_id, result)
                    if failures:
                        raise RuntimeError("; ".join(failures))
                    await asyncio.sleep(0.1)
                tree.status = "complete"
                db.commit()
                try:
                    from vendoo_studio.services.catalog_index import mark_catalog_index_stale
                    import threading
                    mark_catalog_index_stale()

                    def _rebuild() -> None:
                        from vendoo_studio.database import SessionLocal
                        from vendoo_studio.services.catalog_index import rebuild_catalog_index
                        try:
                            with SessionLocal() as session:
                                rebuild_catalog_index(session)
                        except Exception:
                            pass

                    threading.Thread(target=_rebuild, name="catalog-index-rebuild", daemon=True).start()
                except Exception:
                    pass
            except (Exception, asyncio.CancelledError) as error:
                db.rollback()
                tree = db.get(CategoryTree, marketplace)
                tree.status, tree.error = "paused", str(error) or "Extraction interrupted; resume to continue"
                db.commit()
                if isinstance(error, asyncio.CancelledError):
                    raise


def start_sync() -> None:
    global _task
    if not syncing():
        _task = asyncio.create_task(extract_trees())
        _task.add_done_callback(_resume_queued_jobs)


def _resume_queued_jobs(task: asyncio.Task) -> None:
    from vendoo_studio.routes.extension import dispatch_queued_jobs
    if not task.cancelled():
        asyncio.create_task(dispatch_queued_jobs())
