"""Choose a real terminal category independently for each Vendoo form."""
import asyncio
import json
import re

from vendoo_studio.models.catalog import CategoryTree, CategoryTreeNode
from vendoo_studio.providers.xiaomi_mimo import unpack_stream_item
from vendoo_studio.services.catalog_index import search_catalog
from vendoo_studio.services.category_lookup import condense_category_search_query
from vendoo_studio.services.listing_completion import parse_resolution
from vendoo_studio.services.registry import WOMEN_TOPS_SEEDS

DEFAULT_TOP_K = 15
_SELLER_QUESTION_RE = re.compile(
    r"\b(please|confirm|additional details?|tell me|what (?:is|are)|is (?:this|the)|"
    r"or provide|which (?:is|are)|can you|could you|vintage\b.*\?)\b|\?",
    re.I,
)
_WOMEN_RE = re.compile(r"\bwomen(?:['’]s)?\b", re.I)
_TOP_INTENT_RE = re.compile(r"\btops?\b|\bt-?shirts?\b|\btees?\b|\bblouses?\b|\bshirts?\b", re.I)
_NON_TOP_INTENT_RE = re.compile(
    r"\bjeans?\b|\bpants?\b|\bskirts?\b|\bshorts?\b|\bdresses?\b|\bjackets?\b|"
    r"\bcoats?\b|\bhoodies?\b|\bsweatshirts?\b|\bsweaters?\b",
    re.I,
)
_TOP_NOISE_RE = re.compile(
    r"\bcrop\b|\bhalter\b|\btube\b|\blaptop\b|\bslipper|\bflats?\b|\bheadband|"
    r"\bhats?\b|\bwallets?\b|\bswim|\bbikini|\bmaternity\b|\bactivewear\b|\bvintage\b",
    re.I,
)


def _terminal_node(db, marketplace: str, path: str) -> CategoryTreeNode | None:
    from sqlalchemy import func

    path = str(path or "").strip()
    if not path:
        return None
    node = db.query(CategoryTreeNode).filter_by(marketplace=marketplace, path=path).first()
    if node and node.is_leaf and not node.has_children:
        return node
    # Tree extracts sometimes differ in casing ("Tops & blouses" vs "Tops & Blouses").
    node = (
        db.query(CategoryTreeNode)
        .filter(
            CategoryTreeNode.marketplace == marketplace,
            func.lower(CategoryTreeNode.path) == path.casefold(),
            CategoryTreeNode.is_leaf.is_(True),
            CategoryTreeNode.has_children.is_(False),
        )
        .first()
    )
    return node


def _candidate_query(analysis: str, notes: str, override: str = "") -> str:
    """Catalog search must stay short; full analysis is only for the classifier model."""
    return condense_category_search_query(analysis, notes, override=override)


def _women_tops_intent(*texts: str) -> bool:
    joined = "\n".join(str(text or "") for text in texts)
    if not _WOMEN_RE.search(joined) or not _TOP_INTENT_RE.search(joined):
        return False
    # Explicit non-top garments win over a stray "top" word.
    if re.search(r"\b(women(?:['’]s)?\s+)?(jeans?|pants?|dresses?)\b", joined, re.I) and not re.search(
        r"\b(women(?:['’]s)?\s+)?(tops?|t-?shirts?|tees?|blouses?|shirts?)\b", joined, re.I,
    ):
        return False
    if _NON_TOP_INTENT_RE.search(joined) and not re.search(
        r"\b(tops?|t-?shirts?|tees?|blouses?)\b", joined, re.I,
    ):
        return False
    return True


def _preferred_seed_paths(marketplace: str, analysis: str, notes: str, override: str = "") -> list[str]:
    if not _women_tops_intent(analysis, notes, override):
        return []
    return list(WOMEN_TOPS_SEEDS.get(marketplace) or [])


def _search_retry_hint(question: str) -> str:
    """Internal catalog retry phrase only — never seller interview text."""
    text = str(question or "").strip()
    if not text or _SELLER_QUESTION_RE.search(text):
        return ""
    hint = condense_category_search_query(text)
    if not hint or len(hint.split()) > 6:
        return ""
    return hint


def _fallback_node(choices: list[dict], nodes: dict[str, CategoryTreeNode]) -> CategoryTreeNode | None:
    for row in choices or []:
        node = nodes.get(str(row.get("id") or ""))
        if node is not None:
            return node
    return None


async def _ask_model(provider, analysis: str, notes: str, choices: dict) -> dict:
    messages = [{"role": "system", "content": (
        "Classify this product from photo evidence and seller facts separately for each marketplace. "
        "Choose exactly one supplied category id per marketplace from the candidate list. "
        "Match the actual product type and intended department; never infer department solely from size. "
        "Do not use a General breadcrumb for another marketplace. "
        "Marketplace leaf labels differ: General/eBay may say Tops while Poshmark/Mercari/Depop/Etsy use "
        "Tees, T-shirts, or Blouses — those are valid women's top mappings. Always pick the closest "
        "supplied candidate. Never ask the seller anything and never claim a marketplace lacks tops. "
        "If candidates look noisy, put a short product-type search phrase in question "
        "(e.g. \"women tops\") for an internal retry only. Return JSON "
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


def _leaf_query_under(db, marketplace: str, path_prefix: str) -> list[CategoryTreeNode]:
    prefix = path_prefix.rstrip()
    rows = db.query(CategoryTreeNode).filter_by(
        marketplace=marketplace, is_leaf=True, has_children=False,
    ).order_by(CategoryTreeNode.path).all()
    if not prefix:
        return rows
    return [node for node in rows if node.path == prefix or node.path.startswith(prefix + " >")]


def _leaves_matching_query(
    db,
    marketplace: str,
    query: str,
    path_prefix: str = "",
    *,
    limit: int = DEFAULT_TOP_K,
) -> list[CategoryTreeNode]:
    """Use the complete tree when semantic search misses — rank leaves by query tokens."""
    rows = _leaf_query_under(db, marketplace, path_prefix)
    tokens = [token for token in re.findall(r"[a-z0-9']+", (query or "").casefold()) if len(token) > 2]
    if not rows:
        return []
    if not tokens:
        return rows[:limit]
    scored: list[tuple[int, CategoryTreeNode]] = []
    for node in rows:
        path_l = (node.path or "").casefold()
        score = sum(1 for token in tokens if token in path_l)
        if score:
            scored.append((score, node))
    scored.sort(key=lambda item: (-item[0], item[1].path or ""))
    return [node for _, node in scored[:limit]] or rows[:limit]


def _collect_choices(
    db,
    marketplaces: list[str],
    query: str,
    selected: dict[str, str],
    path_prefix: str,
    *,
    analysis: str = "",
    notes: str = "",
    override: str = "",
) -> tuple[dict[str, list[dict]], dict[str, dict[str, CategoryTreeNode]]]:
    choices: dict[str, list[dict]] = {}
    nodes_by_marketplace: dict[str, dict[str, CategoryTreeNode]] = {}
    women_tops = _women_tops_intent(analysis, notes, override, query)
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
        if not hits:
            hits = [{
                "id": node.category_id,
                "path": node.path,
                "label": node.label,
            } for node in _leaves_matching_query(db, marketplace, query, prefix)]

        ordered: list[CategoryTreeNode] = []
        seen_ids: set[str] = set()

        def _take(node: CategoryTreeNode | None) -> None:
            if node is None or node.category_id in seen_ids:
                return
            if prefix and not node.path.startswith(prefix.rstrip() + " >") and node.path != prefix:
                return
            seen_ids.add(node.category_id)
            ordered.append(node)

        for path in _preferred_seed_paths(marketplace, analysis, notes, override):
            _take(_terminal_node(db, marketplace, path))

        search_nodes: list[CategoryTreeNode] = []
        for hit in hits:
            node = db.get(CategoryTreeNode, (marketplace, str(hit.get("id") or "")))
            if node is None or not node.is_leaf or node.has_children:
                continue
            search_nodes.append(node)

        if women_tops:
            clean = [node for node in search_nodes if not _TOP_NOISE_RE.search(node.path or "")]
            noisy = [node for node in search_nodes if _TOP_NOISE_RE.search(node.path or "")]
            for node in clean + noisy:
                _take(node)
        else:
            for node in search_nodes:
                _take(node)

        if not ordered:
            raise RuntimeError(
                f"Could not find verified {marketplace} category candidates. "
                "Retry category selection or name the category more specifically."
            )
        nodes_by_marketplace[marketplace] = {node.category_id: node for node in ordered}
        choices[marketplace] = [
            {"id": node.category_id, "path": node.path, "leaf": True}
            for node in ordered[:DEFAULT_TOP_K]
        ]
    return choices, nodes_by_marketplace


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
    choices, nodes_by_marketplace = _collect_choices(
        db, marketplaces, query, selected, path_prefix,
        analysis=analysis, notes=notes, override=override,
    )

    if not choices:
        return selected

    response = await _ask_model(provider, analysis, notes, choices)
    retry_hint = _search_retry_hint(str(response.get("question") or ""))
    if retry_hint and retry_hint.casefold() != query.casefold():
        choices, nodes_by_marketplace = _collect_choices(
            db, marketplaces, retry_hint, selected, path_prefix,
            analysis=analysis, notes=notes, override=override,
        )
        response = await _ask_model(provider, analysis, notes, choices)
    response.pop("question", None)

    pending = dict(choices)
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

    # Trees are complete mappings — seeded aliases / catalog ranking choose when the model will not.
    for marketplace in failed:
        node = _fallback_node(pending.get(marketplace) or [], nodes_by_marketplace.get(marketplace) or {})
        if node is None:
            raise RuntimeError(
                f"Could not choose a verified {marketplace} category. Retry category selection."
            )
        selected[marketplace] = node.path
    return selected
