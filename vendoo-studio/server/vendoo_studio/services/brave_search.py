from __future__ import annotations

import asyncio
import logging
import re

import httpx

from vendoo_studio.services.keychain import get_brave_api_key

log = logging.getLogger("vendoo_studio.brave_search")

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
ITEM_FIELDS = ("brand", "category", "style", "size", "color", "material", "pattern", "department")
MARKETPLACE_SITES = ("ebay.com", "poshmark.com", "mercari.com", "depop.com", "etsy.com")
# Brave caps count at 20. One 8-result query across five sites usually came back
# with one or two priced listing URLs; per-site queries spread the budget.
BRAVE_RESULT_COUNT = 20
# Brave's free tier allows roughly one request per second, so stagger the fan-out
# rather than firing every query at once.
BRAVE_QUERY_STAGGER_SEC = 0.6
BRAVE_RETRY_SEC = 1.5
_ANALYSIS_FIELD_RE = re.compile(
    r"^-\s*(brand|category|style|size|color|material|pattern|department):\s*(.+?)(?:\s+\(source:.*\))?$",
    re.I | re.M,
)


def fields_from_evidence(evidence: dict | None) -> dict[str, str]:
    found: dict[str, str] = {}
    if not isinstance(evidence, dict):
        return found
    for key in ITEM_FIELDS:
        value = evidence.get(key)
        if isinstance(value, dict):
            raw = value.get("value")
        else:
            raw = value
        text = str(raw or "").strip()
        if text:
            found[key] = text
    return found


def fields_from_analysis(text: str | None) -> dict[str, str]:
    found: dict[str, str] = {}
    for match in _ANALYSIS_FIELD_RE.finditer(text or ""):
        value = match.group(2).strip()
        if value:
            found[match.group(1).lower()] = value
    return found


def item_fields(analysis_text: str | None, evidence: dict | None = None) -> dict[str, str]:
    fields = fields_from_analysis(analysis_text)
    fields.update(fields_from_evidence(evidence))
    return fields


def _query_core(fields: dict[str, str]) -> list[str]:
    brand = fields.get("brand", "").strip()
    # Category arrives as a taxonomy path ("Tops > T-Shirts"); search the leaf.
    category = fields.get("category", "").split(">")[-1].strip()
    style = fields.get("style", "").strip()
    parts = [brand]
    if style:
        parts.append(style)
    if category and category.lower() != style.lower():
        parts.append(category)
    return [part for part in parts if part]


def _query_details(fields: dict[str, str]) -> list[str]:
    """High-signal visible attributes that narrow generic brand/category searches."""
    details: list[str] = []
    for key in ("size", "color", "material", "pattern", "department"):
        value = fields.get(key, "").strip()
        if value and value.lower() not in {part.lower() for part in [*_query_core(fields), *details]}:
            details.append(value)
    return details


def _query_alt(fields: dict[str, str]) -> str:
    """Brand + style, when style says something the category leaf does not."""
    brand = fields.get("brand", "").strip()
    style = fields.get("style", "").strip()
    leaf = (fields.get("category") or "").split(">")[-1].strip()
    if not style or style.lower() == leaf.lower():
        return ""
    return " ".join(part for part in (brand, style) if part)


def sold_comps_query(fields: dict[str, str]) -> str:
    parts = _query_core(fields)
    if not parts:
        return ""
    return " ".join([*parts, *_query_details(fields), "sold comps"])[:400]


def _site_filter() -> str:
    return "(" + " OR ".join(f"site:{site}" for site in MARKETPLACE_SITES) + ")"


def brave_sold_query(fields: dict[str, str]) -> str:
    parts = _query_core(fields)
    if not parts:
        return ""
    return f"{' '.join([*parts, *_query_details(fields)])} sold {_site_filter()}"[:400]


def brave_sold_queries(fields: dict[str, str]) -> list[str]:
    """The broad query first, then one per marketplace so no single site wins the page."""
    broad = brave_sold_query(fields)
    if not broad:
        return []
    core = " ".join([*_query_core(fields), *_query_details(fields)])
    queries = [broad]
    queries.extend(f"{core} sold listing site:{site}" for site in MARKETPLACE_SITES)
    alt = _query_alt(fields)
    if alt:
        queries.append(f"{alt} sold price {_site_filter()}")
    return [query[:400] for query in queries]


def _brave_error(resp: httpx.Response) -> str:
    text = (resp.text or "").strip()
    try:
        payload = resp.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error") or payload.get("message") or payload.get("detail")
        if isinstance(error, dict):
            text = str(error.get("message") or error.get("code") or error)
        elif isinstance(error, str) and error.strip():
            text = error.strip()
    text = " ".join(text.split())
    if len(text) > 240:
        text = text[:237] + "..."
    return f"Brave HTTP {resp.status_code}: {text}" if text else f"Brave HTTP {resp.status_code}"


def format_comp_results(
    query: str,
    results: list[dict],
    *,
    source: str = "Brave Search",
    expected_brand: str = "",
) -> str:
    from vendoo_studio.services.sold_comps import SoldCompsReport, comps_from_web_results, format_sold_comps

    return format_sold_comps(
        SoldCompsReport(
            query=query,
            source=source,
            comps=comps_from_web_results(results, expected_brand=expected_brand),
        )
    )


async def search_web(query: str, api_key: str, *, count: int = 8) -> list[dict]:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            BRAVE_SEARCH_URL,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key,
            },
            params={
                "q": query[:400],
                "count": count,
                "country": "US",
                "search_lang": "en",
                # Sold prices age quickly. Brave defines `py` as pages dated in
                # the last 365 days; disabling spellcheck also preserves exact
                # brand/model spellings instead of silently rewriting them.
                "freshness": "py",
                "result_filter": "web",
                "spellcheck": "false",
                "extra_snippets": "true",
            },
        )
        if resp.status_code >= 400:
            raise RuntimeError(_brave_error(resp))
        payload = resp.json()
    web = payload.get("web") if isinstance(payload, dict) else None
    results = web.get("results") if isinstance(web, dict) else None
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, dict)]


async def test_brave_connection(api_key: str | None = None) -> tuple[bool, str | None]:
    key = (api_key or get_brave_api_key() or "").strip()
    if not key:
        return False, "Add a Brave Search API key in Settings."
    try:
        await search_web("ebay sold listings", key, count=1)
    except Exception as exc:
        return False, str(exc)
    return True, None


async def _search_one(query: str, api_key: str, *, delay: float) -> list[dict]:
    """One staggered query; a 429 from the per-second cap gets a single retry."""
    if delay:
        await asyncio.sleep(delay)
    try:
        return await search_web(query, api_key, count=BRAVE_RESULT_COUNT)
    except Exception as exc:
        if "429" not in str(exc):
            raise
        await asyncio.sleep(BRAVE_RETRY_SEC)
        return await search_web(query, api_key, count=BRAVE_RESULT_COUNT)


async def search_all(queries: list[str], api_key: str) -> tuple[list[dict], list[str]]:
    """Run every query, keep whatever came back, and report the failures."""
    gathered = await asyncio.gather(
        *(
            _search_one(query, api_key, delay=index * BRAVE_QUERY_STAGGER_SEC)
            for index, query in enumerate(queries)
        ),
        return_exceptions=True,
    )
    results: list[dict] = []
    errors: list[str] = []
    for query, outcome in zip(queries, gathered, strict=False):
        if isinstance(outcome, BaseException):
            log.info("Brave sold-comps query failed (%s): %s", query, outcome)
            errors.append(str(outcome))
            continue
        results.extend(outcome)
    return results, errors


async def research_brave_comps(queries: str | list[str], *, expected_brand: str = "") -> str:
    api_key = get_brave_api_key()
    if not api_key:
        return ""
    query_list = [queries] if isinstance(queries, str) else list(queries)
    query_list = [query for query in query_list if query]
    if not query_list:
        return ""
    query = query_list[0]
    try:
        results, errors = await search_all(query_list, api_key)
        if not results and errors:
            raise RuntimeError(errors[0])
        return format_comp_results(query, results, expected_brand=expected_brand)
    except Exception as exc:
        log.warning("Brave sold-comps search failed: %s", exc)
        from vendoo_studio.services.sold_comps import SoldCompsReport, format_sold_comps

        return format_sold_comps(
            SoldCompsReport(
                query=query,
                source="Brave Search",
                note=f"Search failed ({exc}). Use an estimated baseline and note pricing uncertainty in the description.",
            )
        )
