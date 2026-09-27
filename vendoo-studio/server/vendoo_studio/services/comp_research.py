"""Sold comps research: the connected models' own web search, Brave as fallback.

Every connected model (ChatGPT, Cursor, MiMo) searches at once with its native
web search tool, and their comps are merged. Brave runs only when those come
back with fewer than MIN_CONFIDENT_COMPS sold listings, fail, or no model is
connected. ``stream_sold_comps`` reports each source and the merged report as
they land, so the chat and the Regenerate dialog can show progress.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from vendoo_studio.services import live_trace
from vendoo_studio.services.brave_search import (
    brave_sold_queries,
    comp_identities,
    item_fields,
    research_brave_report,
    sold_comps_query,
)
from vendoo_studio.services.chatgpt_oauth import chatgpt_signed_in
from vendoo_studio.services.keychain import get_api_key, get_brave_api_key, get_cursor_api_key
from vendoo_studio.services.sold_comps import (
    MIN_CONFIDENT_COMPS,
    SoldCompsReport,
    comps_from_model_answer,
    format_sold_comps,
    merge_reports,
    research_note,
)

log = logging.getLogger("vendoo_studio.comp_research")

# How long the model searches get before Brave fills in with what they found.
# Cursor's agent reads listing pages one by one and can run for minutes.
MODEL_SEARCH_TIMEOUT_SEC = 90
# The whole lookup, Brave included. Mobile generate SSE drops when comps stall
# for many minutes on the prior status.
SOLD_COMPS_TIMEOUT_SEC = 120

COMPS_SETUP_NOTE = (
    "Sold comps lookup needs ChatGPT, Cursor or MiMo connected, or a Brave Search API key "
    "in Settings. Listing prices will use an estimated baseline until then."
)
COMPS_THIN_IDENTITY_NOTE = (
    "Not enough brand or item detail from the photos to search sold comps. "
    "Use an estimated baseline and note pricing uncertainty in the description."
)
COMPS_TIMEOUT_NOTE = (
    "Sold comps search timed out. Use an estimated baseline and note pricing "
    "uncertainty in the description."
)
COMPS_FAILED_NOTE = (
    "Sold comps search failed. Use an estimated baseline and note pricing "
    "uncertainty in the description."
)

COMPS_SEARCH_PROMPT = (
    "You are researching prices for a secondhand marketplace listing. "
    "Search the live web for recently sold comps on eBay, Poshmark, Mercari, Depop, and Etsy. "
    "Find as many as you can — aim for at least six across two or more of those "
    "marketplaces, up to fifteen. Run several searches with different wording rather "
    "than stopping at the first page of results, but answer within about a minute: "
    "after roughly eight searches, return what you have. "
    "Keep only specific sold items with a real sold price. Ignore how-to articles, "
    "search pages, Terapeak marketing, and pricing guides. "
    "Every comp must match the requested brand and item type; prefer the same style, "
    "size, color, material, and department when those details are present. Exclude lots, "
    "bundles, replacement parts, reproductions, and different models or collaborations. "
    "Require explicit evidence that the item sold or the listing completed, not merely "
    "that it is listed. A seller's lifetime \"items sold\" count is not that evidence. "
    "If a result shows multiple prices, use only the amount explicitly identified as the "
    "sold price; otherwise skip it. A number in the title, or one labeled retail, MSRP, "
    "was, original, or shipping, is not the sold price. "
    "Also list up to eight similar items that are still for sale, with their current "
    "asking price, under \"live\". Never put a listing that is still for sale in \"comps\". "
    "Return JSON only in this shape: "
    '{"market":"$18-$25","comps":[{"title":"...","price":22,"marketplace":"eBay",'
    '"condition":"Good","url":"https://www.ebay.com/itm/123"}],'
    '"live":[{"title":"...","price":30,"marketplace":"Poshmark",'
    '"url":"https://poshmark.com/listing/abc"}]} '
    "Each entry must have the exact listing URL you observed "
    "(ebay.com/itm, poshmark.com/listing, mercari.com/us/item, "
    "depop.com/products, etsy.com/listing). Do not write a listing. Do not invent "
    "prices or URLs. If you find nothing, return {\"market\":\"\",\"comps\":[],\"live\":[]}."
)


def comps_search_messages(query: str) -> list[dict]:
    return [
        {"role": "system", "content": COMPS_SEARCH_PROMPT},
        {"role": "user", "content": f"Find recently sold marketplace comps for: {query}"},
    ]


Searcher = Callable[[list[dict]], Awaitable[dict]]


@dataclass(frozen=True)
class ModelSearch:
    label: str
    search: Searcher


def model_searches() -> list[ModelSearch]:
    """Every connected model with a native web search tool."""
    searches: list[ModelSearch] = []
    if chatgpt_signed_in():
        from vendoo_studio.providers.chatgpt_codex import ChatGPTCodexProvider

        searches.append(ModelSearch("ChatGPT", ChatGPTCodexProvider().web_search))
    cursor_key = get_cursor_api_key()
    if cursor_key:
        from vendoo_studio.providers.cursor_agent import CursorProvider

        searches.append(ModelSearch("Cursor", CursorProvider(api_key=cursor_key).web_search))
    mimo_key = get_api_key()
    if mimo_key:
        from vendoo_studio.providers.xiaomi_mimo import MiMoProvider

        searches.append(ModelSearch("MiMo", MiMoProvider(api_key=mimo_key).web_search))
    return searches


def comps_search_available() -> bool:
    return bool(model_searches()) or bool(get_brave_api_key())


def comps_setup_note() -> str:
    """Shown when generate runs with nothing configured to search comps."""
    return format_sold_comps(
        SoldCompsReport(query="", source="not configured", note=COMPS_SETUP_NOTE)
    )


def _comps_note(query: str, source: str, note: str) -> str:
    return format_sold_comps(SoldCompsReport(query=query, source=source, note=note))


def model_report(
    label: str,
    query: str,
    answer: str,
    sources: list[dict],
    *,
    expected_names: tuple[str, ...] = (),
) -> SoldCompsReport:
    market, comps, live = comps_from_model_answer(answer, sources, expected_names=expected_names)
    return SoldCompsReport(
        query=query,
        source=label,
        comps=comps,
        market=market,
        note="" if comps else research_note(answer),
        live=live,
    )


async def _run_model_search(
    search: ModelSearch, query: str, expected_names: tuple[str, ...]
) -> SoldCompsReport:
    result = await search.search(comps_search_messages(query))
    answer = str(result.get("answer") or "")
    sources = result.get("sources") if isinstance(result.get("sources"), list) else []
    return model_report(
        search.label,
        query,
        answer,
        [item for item in sources if isinstance(item, dict)],
        expected_names=expected_names,
    )


@dataclass(frozen=True)
class CompsEvent:
    """``source``: one source changed state. ``report``: the merged comps so far.
    ``done``: the final comps text."""

    kind: str
    source: str = ""
    state: str = ""
    sold: int = 0
    live: int = 0
    detail: str = ""
    text: str = ""


def _found(report: SoldCompsReport) -> str:
    return f"{len(report.comps)} sold, {len(report.live)} live"


async def _stream_sold_comps(fields: dict[str, str]) -> AsyncIterator[CompsEvent]:
    query = sold_comps_query(fields)
    if not query:
        yield CompsEvent("done", text=_comps_note("", "photo analysis", COMPS_THIN_IDENTITY_NOTE))
        return
    expected_names = comp_identities(fields)
    searches = model_searches()
    brave_key = get_brave_api_key()
    if not searches and not brave_key:
        yield CompsEvent("done", text=comps_setup_note())
        return

    reports: list[SoldCompsReport] = []
    errors: list[str] = []
    tasks = {
        asyncio.create_task(_run_model_search(search, query, expected_names)): search.label
        for search in searches
    }
    for label in tasks.values():
        live_trace.emit("step", f"{label} is searching the web for sold comps")
        yield CompsEvent("source", source=label, state="searching")

    loop = asyncio.get_running_loop()
    deadline = loop.time() + MODEL_SEARCH_TIMEOUT_SEC
    pending = set(tasks)
    try:
        while pending:
            done, pending = await asyncio.wait(
                pending,
                timeout=max(0.0, deadline - loop.time()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                break
            for task in done:
                label = tasks[task]
                try:
                    report = task.result()
                except Exception as exc:
                    log.warning("%s sold-comps search failed: %s", label, exc)
                    errors.append(f"{label}: {exc}")
                    live_trace.emit("step", f"{label} web search failed")
                    yield CompsEvent("source", source=label, state="failed", detail=str(exc))
                    continue
                reports.append(report)
                live_trace.emit("step", f"{label} found {_found(report)}")
                yield CompsEvent(
                    "source", source=label, state="done",
                    sold=len(report.comps), live=len(report.live),
                )
                yield CompsEvent("report", text=format_sold_comps(merge_reports(query, reports)))
    finally:
        for task in pending:
            task.cancel()
    for task in pending:
        label = tasks[task]
        errors.append(f"{label}: timed out")
        live_trace.emit("step", f"{label} web search timed out")
        yield CompsEvent("source", source=label, state="timeout")

    merged = merge_reports(query, reports)
    if brave_key and len(merged.comps) < MIN_CONFIDENT_COMPS:
        yield CompsEvent("source", source="Brave", state="searching")
        try:
            brave = await research_brave_report(
                brave_sold_queries(fields) or [query],
                expected_names=expected_names,
            )
        except Exception as exc:
            log.warning("Brave sold-comps search failed: %s", exc)
            errors.append(f"Brave: {exc}")
            yield CompsEvent("source", source="Brave", state="failed", detail=str(exc))
        else:
            reports.append(brave)
            yield CompsEvent(
                "source", source="Brave", state="done",
                sold=len(brave.comps), live=len(brave.live),
            )
            merged = merge_reports(query, reports)

    if not reports:
        note = COMPS_FAILED_NOTE
        if errors:
            note = f"{note} ({'; '.join(errors)})"
        yield CompsEvent("done", text=_comps_note(query, "web search", note))
        return
    yield CompsEvent("done", text=format_sold_comps(merged))


async def stream_sold_comps(
    analysis_text: str | None, evidence: dict | None = None
) -> AsyncIterator[CompsEvent]:
    """Progress events for one comps lookup, ending with a ``done`` event."""
    fields = item_fields(analysis_text, evidence)
    stream = _stream_sold_comps(fields)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + SOLD_COMPS_TIMEOUT_SEC
    last_report = ""
    try:
        while True:
            try:
                event = await asyncio.wait_for(
                    anext(stream), timeout=max(0.0, deadline - loop.time())
                )
            except StopAsyncIteration:
                return
            except TimeoutError:
                log.warning("sold comps research timed out after %ss", SOLD_COMPS_TIMEOUT_SEC)
                yield CompsEvent(
                    "done",
                    text=last_report or _comps_note(sold_comps_query(fields), "timed out", COMPS_TIMEOUT_NOTE),
                )
                return
            if event.kind == "report":
                last_report = event.text
            yield event
            if event.kind == "done":
                return
    finally:
        await stream.aclose()


async def research_sold_comps(analysis_text: str | None, evidence: dict | None = None) -> str:
    text = ""
    async for event in stream_sold_comps(analysis_text, evidence):
        if event.kind == "done":
            text = event.text
    return text
