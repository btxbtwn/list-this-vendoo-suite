"""Sold comps research: the listing model's own web search, Brave as fallback.

The model that writes listings (Settings → Listing AI: the primary when it is
connected, else the fallback) searches with its native web search tool. Brave
supplements thin sold or active results, and runs when no model is connected.
``stream_sold_comps`` reports each source and the report as they land, so the chat and the Regenerate dialog can show progress.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from vendoo_studio.config import skills_dir
from vendoo_studio.services import live_trace
from vendoo_studio.services.brave_search import (
    brave_active_queries,
    brave_sold_queries,
    comp_identities,
    item_fields,
    research_brave_report,
    sold_comps_query,
)
from vendoo_studio.services.keychain import get_brave_api_key
from vendoo_studio.services.listing_provider import get_listing_provider
from vendoo_studio.services.sold_comps import (
    MIN_CONFIDENT_COMPS,
    SoldCompsReport,
    comps_from_model_answer,
    format_sold_comps,
    merge_reports,
    research_note,
)

log = logging.getLogger("vendoo_studio.comp_research")

# How long the model's search gets before Brave takes over.
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



def comps_search_messages(query: str) -> list[dict]:
    prompt = (skills_dir() / "list-this" / "references" / "comp-research.md").read_text(encoding="utf-8")
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"Find recently sold comps and active marketplace listings for: {query}"},
    ]


Searcher = Callable[[list[dict]], Awaitable[dict]]


@dataclass(frozen=True)
class ModelSearch:
    label: str
    search: Searcher


_PROVIDER_LABELS = {"chatgpt": "ChatGPT", "cursor": "Cursor", "xiaomi-mimo": "MiMo"}


def model_search() -> ModelSearch | None:
    """The listing model's native web search, or None when no model is connected."""
    provider = get_listing_provider()
    if provider is None:
        return None
    return ModelSearch(_PROVIDER_LABELS.get(provider.name, provider.name), provider.web_search)


def comps_search_available() -> bool:
    return model_search() is not None or bool(get_brave_api_key())


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
    search = model_search()
    brave_key = get_brave_api_key()
    if search is None and not brave_key:
        yield CompsEvent("done", text=comps_setup_note())
        return

    reports: list[SoldCompsReport] = []
    errors: list[str] = []
    if search is not None:
        label = search.label
        live_trace.emit("step", f"{label} is searching the web for sold comps")
        yield CompsEvent("source", source=label, state="searching")
        try:
            report = await asyncio.wait_for(
                _run_model_search(search, query, expected_names),
                timeout=MODEL_SEARCH_TIMEOUT_SEC,
            )
        except TimeoutError:
            errors.append(f"{label}: timed out")
            live_trace.emit("step", f"{label} web search timed out")
            yield CompsEvent("source", source=label, state="timeout")
        except Exception as exc:
            log.warning("%s sold-comps search failed: %s", label, exc)
            errors.append(f"{label}: {exc}")
            live_trace.emit("step", f"{label} web search failed")
            yield CompsEvent("source", source=label, state="failed", detail=str(exc))
        else:
            reports.append(report)
            live_trace.emit("step", f"{label} found {_found(report)}")
            yield CompsEvent(
                "source", source=label, state="done",
                sold=len(report.comps), live=len(report.live),
            )
            yield CompsEvent("report", text=format_sold_comps(report))

    # Supplement only the side of the research that is still too thin.
    merged = merge_reports(query, reports)
    queries: list[str] = []
    if len(merged.comps) < MIN_CONFIDENT_COMPS:
        queries.extend(brave_sold_queries(fields))
    if len(merged.live) < MIN_CONFIDENT_COMPS:
        queries.extend(brave_active_queries(fields))
    if brave_key and queries:
        yield CompsEvent("source", source="Brave", state="searching")
        try:
            brave = await research_brave_report(
                queries,
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
            yield CompsEvent("report", text=format_sold_comps(merge_reports(query, reports)))

    if not reports:
        note = COMPS_FAILED_NOTE
        if errors:
            note = f"{note} ({'; '.join(errors)})"
        yield CompsEvent("done", text=_comps_note(query, "web search", note))
        return
    yield CompsEvent("done", text=format_sold_comps(merge_reports(query, reports)))


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
