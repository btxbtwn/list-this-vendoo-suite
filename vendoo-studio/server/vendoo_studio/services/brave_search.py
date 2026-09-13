from __future__ import annotations

import logging
import re

import httpx

from vendoo_studio.services.keychain import get_brave_api_key

log = logging.getLogger("vendoo_studio.brave_search")

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
ITEM_FIELDS = ("brand", "category", "style", "size", "color")
_ANALYSIS_FIELD_RE = re.compile(
    r"^-\s*(brand|category|style|size|color):\s*(.+?)(?:\s+\(source:.*\))?$",
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
    item = (fields.get("category") or fields.get("style") or "").strip()
    return [part for part in (brand, item) if part]


def sold_comps_query(fields: dict[str, str]) -> str:
    parts = _query_core(fields)
    if not parts:
        return ""
    return " ".join([*parts, "sold comps"])[:400]


def brave_sold_query(fields: dict[str, str]) -> str:
    parts = _query_core(fields)
    if not parts:
        return ""
    core = " ".join(parts)
    return (
        f"{core} sold (site:ebay.com OR site:poshmark.com OR site:mercari.com "
        "OR site:depop.com OR site:etsy.com)"
    )[:400]


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


def format_comp_results(query: str, results: list[dict], *, source: str = "Brave Search") -> str:
    from vendoo_studio.services.sold_comps import SoldCompsReport, comps_from_web_results, format_sold_comps

    return format_sold_comps(
        SoldCompsReport(
            query=query,
            source=source,
            comps=comps_from_web_results(results),
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


async def research_brave_comps(query: str) -> str:
    api_key = get_brave_api_key()
    if not api_key:
        return ""
    try:
        results = await search_web(query, api_key)
        return format_comp_results(query, results)
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
