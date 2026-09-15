"""Choose a real terminal category independently for each Vendoo form."""
import asyncio
import json

from vendoo_studio.models.catalog import CategoryTree, CategoryTreeNode
from vendoo_studio.providers.xiaomi_mimo import unpack_stream_item
from vendoo_studio.services.catalog_index import search_catalog
from vendoo_studio.services.listing_completion import parse_resolution

DEFAULT_TOP_K = 15


def _terminal_node(db, marketplace: str, path: str) -> CategoryTreeNode | None:
    node = db.query(CategoryTreeNode).filter_by(marketplace=marketplace, path=path).first()
    if node and node.is_leaf and not node.has_children:
        return node
    return None


def _candidate_query(analysis: str, notes: str, override: str = "") -> str:
    parts = [str(analysis or "").strip(), str(notes or "").strip()]
    if override:
        parts.append(override)
    return "\n".join(part for part in parts if part)


async def _ask_model(provider, analysis: str, notes: str, choices: dict) -> dict:
    messages = [{"role": "system", "content": (
        "Classify this product from photo evidence and seller facts separately for each marketplace. "
        "Choose exactly one supplied category id per marketplace from the candidate list. "
        "Match the actual product type and intended department; never infer department solely from size. "
        "Do not use a General breadcrumb for another marketplace. If the evidence is insufficient or no "
        "choice fits, ask the seller a specific question instead of guessing. Return JSON "
        '{"categories": {"marketplace": "category id"}, "question": ""}.'
    )}, {"role": "user", "content": json.dumps({
        "photo_analysis": analysis,
        "seller_details": notes,
        "choices": choices,
    }, ensure_ascii=False)}]
    text = ""
    async with asyncio.timeout(120):
        async for chunk in provider.chat(messages, stream=True):
            kind, value = unpack_stream_item(chunk)
            if kind != "thinking":
                text += value or ""
    return parse_resolution(text)


async def select_categories(
    db,
    provider,
    analysis: str,
    notes: str,
    platforms: list[str],
    override: str = "",
) -> dict:
    marketplaces = ["general", *platforms]
    missing = [mp for mp in marketplaces if not (tree := db.get(CategoryTree, mp)) or tree.status != "complete"]
    if missing:
        raise RuntimeError("Finish category-tree extraction before generating: " + ", ".join(missing))

    selected: dict[str, str] = {}
    path_prefix = ""
    if override:
        node = db.query(CategoryTreeNode).filter_by(marketplace="general", path=override).first()
        if not node:
            raise RuntimeError("The selected General category is not in Vendoo's tree. Choose a current category.")
        if node.is_leaf and not node.has_children:
            selected["general"] = node.path
        else:
            path_prefix = node.path

    query = _candidate_query(analysis, notes, override)
    choices: dict[str, list[dict]] = {}
    nodes_by_marketplace: dict[str, dict[str, CategoryTreeNode]] = {}
    for marketplace in marketplaces:
        if marketplace in selected:
            continue
        prefix = path_prefix if marketplace == "general" else ""
        hits = search_catalog(
            db,
            query,
            marketplace=marketplace,
            kind="category",
            top_k=DEFAULT_TOP_K,
            path_prefix=prefix,
        )
        if not hits and prefix:
            # Parent override with no semantic hits — fall back to direct children leaves under that branch.
            hits = [{
                "id": node.category_id,
                "path": node.path,
                "label": node.label,
            } for node in _leaf_query_under(db, marketplace, prefix)[:DEFAULT_TOP_K]]
        verified = []
        nodes: dict[str, CategoryTreeNode] = {}
        for hit in hits:
            node = db.get(CategoryTreeNode, (marketplace, str(hit.get("id") or "")))
            if node is None or not node.is_leaf or node.has_children:
                continue
            if prefix and not node.path.startswith(prefix.rstrip() + " >") and node.path != prefix:
                continue
            nodes[node.category_id] = node
            verified.append({"id": node.category_id, "path": node.path, "leaf": True})
        if not verified:
            raise RuntimeError(
                f"Could not find verified {marketplace} category candidates. "
                "Retry category selection or name the category more specifically."
            )
        choices[marketplace] = verified
        nodes_by_marketplace[marketplace] = nodes

    if not choices:
        return selected

    response = await _ask_model(provider, analysis, notes, choices)
    if response.get("question"):
        raise RuntimeError(str(response["question"]))

    pending = dict(choices)
    for attempt in range(2):
        failed: list[str] = []
        for marketplace, nodes in nodes_by_marketplace.items():
            if marketplace in selected:
                continue
            category_id = str((response.get("categories") or {}).get(marketplace) or "")
            node = nodes.get(category_id)
            if node is None:
                failed.append(marketplace)
                continue
            selected[marketplace] = node.path
        if not failed:
            return selected
        if attempt == 0:
            retry_choices = {mp: pending[mp] for mp in failed if mp in pending}
            response = await _ask_model(provider, analysis, notes, retry_choices)
            if response.get("question"):
                raise RuntimeError(str(response["question"]))
            continue
        raise RuntimeError(
            f"Could not choose a verified {failed[0]} category. Retry category selection."
        )
    raise RuntimeError("Could not choose a verified category. Retry category selection.")


def _leaf_query_under(db, marketplace: str, path_prefix: str) -> list[CategoryTreeNode]:
    prefix = path_prefix.rstrip()
    rows = db.query(CategoryTreeNode).filter_by(
        marketplace=marketplace, is_leaf=True, has_children=False,
    ).order_by(CategoryTreeNode.path).all()
    return [node for node in rows if node.path == prefix or node.path.startswith(prefix + " >")]
