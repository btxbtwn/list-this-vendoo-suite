from __future__ import annotations

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


async def research_sold_comps(analysis_text: str | None, evidence: dict | None = None) -> str:
    fields = item_fields(analysis_text, evidence)
    query = sold_comps_query(fields)
    if not query:
        return ""

    chatgpt_text = ""
    if chatgpt_signed_in():
        try:
            chatgpt_text = await research_chatgpt_comps(query)
            if comps_usable(chatgpt_text):
                return chatgpt_text
            log.info("ChatGPT sold-comps search was thin; trying Brave")
        except Exception as exc:
            log.warning("ChatGPT sold-comps search failed: %s", exc)

    if get_brave_api_key():
        brave_query = brave_sold_query(fields) or query
        brave_text = await research_brave_comps(brave_query)
        if comps_usable(brave_text):
            return brave_text

    if chatgpt_text:
        return chatgpt_text
    return ""
