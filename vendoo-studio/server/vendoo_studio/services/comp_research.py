from __future__ import annotations

import asyncio
import logging

from vendoo_studio.services.brave_search import (
    brave_sold_query,
    item_fields,
    research_brave_comps,
    sold_comps_query,
)
from vendoo_studio.services.chatgpt_oauth import chatgpt_signed_in
from vendoo_studio.services.keychain import get_brave_api_key
from vendoo_studio.services.sold_comps import (
    SoldCompsReport,
    comps_from_chatgpt,
    comps_usable,
    format_sold_comps,
    research_note,
)

log = logging.getLogger("vendoo_studio.comp_research")

# Mobile generate SSE drops when comps stall for many minutes on the prior status.
SOLD_COMPS_TIMEOUT_SEC = 90
# How long a usable Brave result waits for ChatGPT comps before winning.
CHATGPT_GRACE_SEC = 15


def comps_search_available() -> bool:
    return chatgpt_signed_in() or bool(get_brave_api_key())


def format_chatgpt_comps(query: str, answer: str, sources: list[dict]) -> str:
    market, comps = comps_from_chatgpt(answer, sources)
    return format_sold_comps(
        SoldCompsReport(
            query=query,
            source="ChatGPT web search",
            comps=comps,
            market=market,
            note="" if comps else research_note(answer),
        )
    )


async def research_chatgpt_comps(query: str) -> str:
    from vendoo_studio.providers.chatgpt_codex import ChatGPTCodexProvider

    result = await ChatGPTCodexProvider().web_search(query)
    answer = str(result.get("answer") or "")
    sources = result.get("sources") if isinstance(result.get("sources"), list) else []
    return format_chatgpt_comps(query, answer, [item for item in sources if isinstance(item, dict)])


async def _research_sold_comps(analysis_text: str | None, evidence: dict | None = None) -> str:
    """Search ChatGPT and Brave at once; prefer usable ChatGPT comps, else the first usable result."""
    fields = item_fields(analysis_text, evidence)
    query = sold_comps_query(fields)
    if not query:
        return ""

    tasks: dict[str, asyncio.Task] = {}
    if chatgpt_signed_in():
        tasks["chatgpt"] = asyncio.create_task(research_chatgpt_comps(query))
    if get_brave_api_key():
        tasks["brave"] = asyncio.create_task(research_brave_comps(brave_sold_query(fields) or query))
    if not tasks:
        return ""

    names = {task: name for name, task in tasks.items()}
    results: dict[str, str] = {}
    loop = asyncio.get_running_loop()
    chatgpt_deadline: float | None = None
    pending = set(tasks.values())
    try:
        while pending:
            timeout = None if chatgpt_deadline is None else max(0.0, chatgpt_deadline - loop.time())
            done, pending = await asyncio.wait(pending, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                log.info("ChatGPT sold-comps search exceeded the grace window; using Brave")
                break
            for task in done:
                name = names[task]
                try:
                    results[name] = task.result() or ""
                except Exception as exc:
                    log.warning("%s sold-comps search failed: %s", name, exc)
                    results[name] = ""
            if comps_usable(results.get("chatgpt")):
                return results["chatgpt"]
            if comps_usable(results.get("brave")) and tasks.get("chatgpt") in pending:
                # ChatGPT comps are richer; give it a short head start before settling for Brave.
                chatgpt_deadline = chatgpt_deadline or loop.time() + CHATGPT_GRACE_SEC
    finally:
        for task in pending:
            task.cancel()

    if comps_usable(results.get("brave")):
        return results["brave"]
    return results.get("chatgpt") or ""


async def research_sold_comps(analysis_text: str | None, evidence: dict | None = None) -> str:
    try:
        return await asyncio.wait_for(
            _research_sold_comps(analysis_text, evidence),
            timeout=SOLD_COMPS_TIMEOUT_SEC,
        )
    except TimeoutError:
        log.warning("sold comps research timed out after %ss", SOLD_COMPS_TIMEOUT_SEC)
        return ""
