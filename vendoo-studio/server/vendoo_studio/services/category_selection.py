"""Choose a real terminal category independently for each Vendoo form."""
import asyncio
import json

from vendoo_studio.models.catalog import CategoryTree, CategoryTreeNode
from vendoo_studio.providers.xiaomi_mimo import unpack_stream_item
from vendoo_studio.services.listing_completion import parse_resolution


async def select_categories(db, provider, analysis: str, notes: str, platforms: list[str], override: str = "") -> dict:
    marketplaces = ["general", *platforms]
    missing = [mp for mp in marketplaces if not (tree := db.get(CategoryTree, mp)) or tree.status != "complete"]
    if missing:
        raise RuntimeError("Finish category-tree extraction before generating: " + ", ".join(missing))
    parents = {mp: "__root" for mp in marketplaces}
    selected = {}
    if override:
        node = db.query(CategoryTreeNode).filter_by(marketplace="general", path=override).first()
        if not node:
            raise RuntimeError("The selected General category is not in Vendoo's tree. Choose a current category.")
        if node.is_leaf:
            selected["general"] = node.path
        else:
            parents["general"] = node.category_id
    for _ in range(16):
        choices = {}
        nodes_by_marketplace = {}
        for marketplace in marketplaces:
            if marketplace in selected:
                continue
            nodes = db.query(CategoryTreeNode).filter_by(marketplace=marketplace, parent_id=parents[marketplace]).all()
            nodes_by_marketplace[marketplace] = {node.category_id: node for node in nodes}
            choices[marketplace] = [{"id": node.category_id, "path": node.path, "leaf": node.is_leaf} for node in nodes]
        if not choices:
            return selected
        messages = [{"role": "system", "content": (
            "Classify this product from photo evidence and seller facts separately for each marketplace. "
            "Choose exactly one supplied category id per marketplace. Branches will expose their children next. "
            "Match the actual product type and intended department; never infer department solely from size. "
            "Do not use a General breadcrumb for another marketplace. If the evidence is insufficient or no "
            "choice fits, ask the seller a specific question instead of guessing. Return JSON "
            '{"categories": {"marketplace": "category id"}, "question": ""}.'
        )}, {"role": "user", "content": json.dumps({"photo_analysis": analysis, "seller_details": notes,
                                                     "choices": choices}, ensure_ascii=False)}]
        text = ""
        async with asyncio.timeout(120):
            async for chunk in provider.chat(messages, stream=True):
                kind, value = unpack_stream_item(chunk)
                if kind != "thinking":
                    text += value or ""
        response = parse_resolution(text)
        if response.get("question"):
            raise RuntimeError(str(response["question"]))
        for marketplace, nodes in nodes_by_marketplace.items():
            category_id = str((response.get("categories") or {}).get(marketplace) or "")
            node = nodes.get(category_id)
            if node is None:
                raise RuntimeError(f"Could not choose a verified {marketplace} category. Retry category selection.")
            if node.is_leaf:
                selected[marketplace] = node.path
            elif node.has_children:
                parents[marketplace] = node.category_id
            else:
                raise RuntimeError(f"{marketplace} category is not selectable: {node.path}")
    raise RuntimeError("Category selection did not reach a terminal category on every form")
