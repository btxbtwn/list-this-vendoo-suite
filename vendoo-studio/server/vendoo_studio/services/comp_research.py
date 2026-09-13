from __future__ import annotations

import logging
import re

from vendoo_studio.services.brave_search import (
    item_fields,
    research_brave_comps,
    sold_comps_query,
)
from vendoo_studio.services.chatgpt_oauth import chatgpt_signed_in
from vendoo_studio.services.keychain import get_brave_api_key

log = logging.getLogger("vendoo_studio.comp_research")

_PRICE_RE = re.compile(r"\$\s*\d")


def comps_search_available() -> bool:
    return chatgpt_signed_in() or bool(get_brave_api_key())


def comps_usable(text: str | None) -> bool:
    if not text or not text.strip():
        return False
    lowered = text.lower()
    if "search failed" in lowered:
        return False
    if "no sold listings found" in lowered and not _PRICE_RE.search(text):
        return False
    return bool(_PRICE_RE.search(text) or "http" in lowered)


def format_chatgpt_comps(query: str, answer: str, sources: list[dict]) -> str:
    lines = ["Sold comps:", f"Query: {query}", "Source: ChatGPT web search"]
    note = (answer or "").strip()
    if note:
        lines.append(note)
    elif sources:
        lines.append("No written summary. Use the sources below.")
    else:
        lines.append(
            "No sold listings found. Use an estimated baseline and note pricing uncertainty in the description."
        )
    if sources:
        lines.append("")
        lines.append("Sources:")
        for item in sources[:8]:
            title = " ".join(str(item.get("title") or "").split())
            url = str(item.get("url") or "").strip()
            description = " ".join(str(item.get("description") or "").split())
            if title:
                lines.append(f"- {title}")
            if description:
                lines.append(f"  {description}")
            if url:
                lines.append(f"  {url}")
    lines.append(
        "Use these live results to set market price, then listing price = market × 1.35 (whole dollars)."
    )
    return "\n".join(lines)


async def research_chatgpt_comps(query: str) -> str:
    from vendoo_studio.providers.chatgpt_codex import ChatGPTCodexProvider

    result = await ChatGPTCodexProvider().web_search(query)
    answer = str(result.get("answer") or "")
    sources = result.get("sources") if isinstance(result.get("sources"), list) else []
    return format_chatgpt_comps(query, answer, [item for item in sources if isinstance(item, dict)])


async def research_sold_comps(analysis_text: str | None, evidence: dict | None = None) -> str:
    query = sold_comps_query(item_fields(analysis_text, evidence))
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
        brave_text = await research_brave_comps(query)
        if comps_usable(brave_text) or (brave_text and "search failed" not in brave_text.lower()):
            return brave_text
        if brave_text:
            return brave_text

    if chatgpt_text:
        return chatgpt_text
    return ""
