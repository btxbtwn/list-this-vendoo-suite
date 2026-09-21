"""Choose a real terminal category independently for each Vendoo form."""
import asyncio
import json
import logging
import re

from sqlalchemy import or_

from vendoo_studio.models.catalog import CategoryTree, CategoryTreeNode
from vendoo_studio.providers.xiaomi_mimo import unpack_stream_item
from vendoo_studio.services.catalog_index import search_catalog
from vendoo_studio.services.category_lookup import (
    condense_category_search_query,
    is_apparel_general,
    is_non_apparel_path,
)
from vendoo_studio.services.listing_completion import parse_resolution
from vendoo_studio.services.registry import WOMEN_TOPS_SEEDS

log = logging.getLogger("vendoo_studio.category_selection")
DEFAULT_TOP_K = 15
# Long enough that a slow answer still beats keyword ranking, which is the only
# other thing that can choose.
SELECTION_TIMEOUT_SEC = 150
# Ceiling on rows pulled in for ranking. Enough for any real query, far short
# of reading a whole marketplace tree into memory.
MAX_RANKED_ROWS = 400
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
# Subtypes that steal a plain scoop-neck / graphic tee or blouse when search ranks by "tee"/"top".
_TOP_NOISE_RE = re.compile(
    r"\bcrop\b|\bhalter\b|\btube\b|\bmuscle\b|\btanks?\b|\btunics?\b|\blaptop\b|\bslipper|\bflats?\b|\bheadband|"
    r"\bhats?\b|\bwallets?\b|\bswim|\bbikini|\bmaternity\b|\bactivewear\b|\bvintage\b",
    re.I,
)
_APPAREL_INTENT_RE = re.compile(
    r"\b(clothing|women|men|kids|girls|boys|tops?|t-?shirts?|tees?|blouses?|shirts?|"
    r"dresses?|jeans?|pants?|skirts?|sweaters?|hoodies?)\b",
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


def _selection_stream(provider, messages: list[dict]):
    """The provider's fastest path that still streams, reasoning skipped."""
    quick = getattr(provider, "quick_chat", None)
    if callable(quick):
        return quick(messages)
    return provider.chat(messages, stream=True)


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


def _apparel_intent(*texts: str) -> bool:
    joined = "\n".join(str(text or "") for text in texts)
    if is_apparel_general(joined):
        return True
    return bool(_APPAREL_INTENT_RE.search(joined)) and not is_non_apparel_path(joined)


def _usable_search_node(
    node: CategoryTreeNode,
    *,
    apparel: bool,
    women_tops: bool,
    context: str = "",
) -> bool:
    path = node.path or ""
    if apparel and is_non_apparel_path(path):
        return False
    if not women_tops:
        return True
    # Only the leaf matters — parent "Crop & Tube Tops" must not veto a Tube Tops
    # listing that never said "crop".
    leaf = path.rsplit(">", 1)[-1]
    for match in _TOP_NOISE_RE.finditer(leaf):
        token = match.group(0)
        forms = {token.casefold(), _singular(token.casefold())}
        if not any(re.search(rf"\b{re.escape(form)}\b", context, re.I) for form in forms):
            return False
    return True


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
    try:
        # Picking one of a handful of supplied paths does not need a reasoning
        # pass, and the reasoning model kept spending the whole budget before
        # answering — leaving keyword ranking to choose, which is how a girls'
        # tee came back as Fastener Nuts. The old budget was kept short so
        # Chrome field discovery could start; the category-specifics endpoint
        # replaced that, so there is nothing waiting on this any more.
        async with asyncio.timeout(SELECTION_TIMEOUT_SEC):
            async for chunk in _selection_stream(provider, messages):
                kind, value = unpack_stream_item(chunk)
                if kind != "thinking":
                    text += value or ""
    except TimeoutError:
        log.warning("category selection model timed out; using catalog ranking")
        return {"categories": {}, "question": ""}
    return parse_resolution(text)


def _escape_like(text: str) -> str:
    """Escape a LIKE pattern so a category label cannot act as a wildcard."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _leaf_query_under(db, marketplace: str, path_prefix: str, *, limit: int | None = None):
    """Leaves under a path, filtered by the database rather than by Python.

    There are ~18k leaves per large marketplace. Reading them all to keep a
    handful is what made every generation cost tens of megabytes of ORM
    objects, and a second of CPU, before the model was even asked.
    """
    query = db.query(CategoryTreeNode).filter_by(
        marketplace=marketplace, is_leaf=True, has_children=False,
    )
    prefix = (path_prefix or "").rstrip()
    if prefix:
        query = query.filter(
            or_(
                CategoryTreeNode.path == prefix,
                CategoryTreeNode.path.like(f"{_escape_like(prefix)} >%", escape="\\"),
            )
        )
    query = query.order_by(CategoryTreeNode.path)
    return query.limit(limit).all() if limit else query.all()


def _query_tokens(query: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9']+", (query or "").casefold()) if len(token) > 2]


_SIBILANT_ES = ("ses", "xes", "zes", "ches", "shes")


def _singular(word: str) -> str:
    """Crude de-pluralisation so "tee" and "Tees" are the same word.

    Only drop "es" after a sibilant ("dresses" -> "dress"); elsewhere it is a
    plain "s" ("tees" -> "tee", not "te").
    """
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(_SIBILANT_ES):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _words(text: str) -> set[str]:
    return {_singular(word) for word in re.findall(r"[a-z0-9']+", text)}


# A token has to be a whole word in the path. Substring matching is how "tee"
# from a t-shirt title scored "Play Teepees" and "Fastener Nuts > Tee Nuts".
def _word_hits(path: str, tokens: list[str]) -> tuple[int, int]:
    """``(hits in the leaf label, hits anywhere)`` for scoring."""
    path_l = (path or "").casefold()
    words = _words(path_l)
    leaf_words = _words(path_l.rsplit(">", 1)[-1])
    wanted = {_singular(token) for token in tokens}
    return (
        len(wanted & leaf_words),
        len(wanted & words),
    )


def _leaves_matching_query(
    db,
    marketplace: str,
    query: str,
    path_prefix: str = "",
    *,
    limit: int = DEFAULT_TOP_K,
) -> list[CategoryTreeNode]:
    """Rank leaves by query tokens, letting SQL discard the ones that cannot match."""
    tokens = _query_tokens(query)
    if not tokens:
        return _leaf_query_under(db, marketplace, path_prefix, limit=limit)

    # Only rows containing at least one token can score, so let SQLite find
    # them. The word check still happens below; this just narrows the set.
    rows = _leaf_query_under_matching(db, marketplace, path_prefix, tokens)
    if not rows:
        return _leaf_query_under(db, marketplace, path_prefix, limit=limit)

    scored: list[tuple[int, int, int, CategoryTreeNode]] = []
    for node in rows:
        leaf_hits, all_hits = _word_hits(node.path or "", tokens)
        if not all_hits:
            continue
        # A token matching the leaf itself ("Tops") means more than one
        # matching an ancestor, and a shorter path breaks ties by specificity
        # rather than by alphabet — which is what let "Business & Industrial"
        # win every tie it was in.
        scored.append((-leaf_hits, -all_hits, len(node.path or ""), node))
    if not scored:
        return _leaf_query_under(db, marketplace, path_prefix, limit=limit)
    scored.sort(key=lambda item: (item[0], item[1], item[2], item[3].path or ""))
    return [node for *_rank, node in scored[:limit]]


def _leaf_query_under_matching(db, marketplace: str, path_prefix: str, tokens: list[str]):
    """Leaves whose path contains any query token, chosen by the database."""
    query = db.query(CategoryTreeNode).filter_by(
        marketplace=marketplace, is_leaf=True, has_children=False,
    )
    prefix = (path_prefix or "").rstrip()
    if prefix:
        query = query.filter(
            or_(
                CategoryTreeNode.path == prefix,
                CategoryTreeNode.path.like(f"{_escape_like(prefix)} >%", escape="\\"),
            )
        )
    query = query.filter(
        or_(*[CategoryTreeNode.path.ilike(f"%{_escape_like(token)}%", escape="\\") for token in tokens])
    )
    # Generous next to the handful returned, but small next to 18k.
    return query.order_by(CategoryTreeNode.path).limit(MAX_RANKED_ROWS).all()


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
    apparel = women_tops or _apparel_intent(analysis, notes, override, query)
    context = "\n".join(str(text or "") for text in (analysis, notes, override, query))
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

        def _take(
            node: CategoryTreeNode | None,
            prefix: str | None = prefix,
            seen_ids: set[str] = seen_ids,
            ordered: list[CategoryTreeNode] = ordered,
        ) -> None:
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
            if not _usable_search_node(
                node, apparel=apparel, women_tops=women_tops, context=context,
            ):
                continue
            search_nodes.append(node)

        for node in search_nodes:
            _take(node)

        # Seeds + filtered search can be empty when the index only returned
        # hardware collisions; fall back to word-ranked clothing leaves.
        if not ordered:
            for node in _leaves_matching_query(db, marketplace, query, prefix):
                if not _usable_search_node(
                    node, apparel=apparel, women_tops=women_tops, context=context,
                ):
                    continue
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
    pending = dict(choices)
    selected_from_model: dict[str, str] = {}
    failed: list[str] = []
    for marketplace, nodes in nodes_by_marketplace.items():
        if marketplace in selected:
            continue
        category_id = str((response.get("categories") or {}).get(marketplace) or "")
        node = nodes.get(category_id)
        if node is None:
            failed.append(marketplace)
            continue
        selected_from_model[marketplace] = node.path

    # Only spend a second model round when most picks failed and the model offered a clean search hint.
    retry_hint = _search_retry_hint(str(response.get("question") or ""))
    need_retry = (
        bool(failed)
        and len(failed) > max(1, len(nodes_by_marketplace) // 2)
        and bool(retry_hint)
        and retry_hint.casefold() != query.casefold()
    )
    if need_retry:
        choices, nodes_by_marketplace = _collect_choices(
            db, marketplaces, retry_hint, selected, path_prefix,
            analysis=analysis, notes=notes, override=override,
        )
        response = await _ask_model(provider, analysis, notes, choices)
        pending = dict(choices)
        selected_from_model = {}
        failed = []
        for marketplace, nodes in nodes_by_marketplace.items():
            if marketplace in selected:
                continue
            category_id = str((response.get("categories") or {}).get(marketplace) or "")
            node = nodes.get(category_id)
            if node is None:
                failed.append(marketplace)
                continue
            selected_from_model[marketplace] = node.path

    selected.update(selected_from_model)
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
