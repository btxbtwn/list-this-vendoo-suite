from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from vendoo_studio.config import user_data_root
from vendoo_studio.providers.xiaomi_mimo import (
    VISION_MAX_SIDE,
    StreamChunk,
    encode_images,
    unpack_stream_item,
)
from vendoo_studio.services import claude_auth, live_trace
from vendoo_studio.services.user_settings import get_claude_models, resolved_claude_models

log = logging.getLogger("vendoo_studio.claude")

TEXT_ONLY_PREAMBLE = (
    "You are a product listing assistant for Vendoo Listing Studio. "
    "Reply with assistant text only. "
    "When asked for JSON, return only valid JSON with no markdown fences."
)
WEB_SEARCH_PREAMBLE = (
    "You are a research assistant for Vendoo Listing Studio. Use only web search and "
    "web fetch. When asked for JSON, return only valid JSON with no markdown fences."
)
WEB_TOOLS = ["WebSearch", "WebFetch"]
WEB_SEARCH_MAX_TURNS = 12
SIGNED_OUT = "Claude is signed out. Sign in with Claude in Settings."


def listing_scratch_dir() -> Path:
    path = user_data_root() / "claude-listing-workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _image_block(url: str) -> dict | None:
    if url.startswith("data:"):
        header, _, data = url.partition(",")
        if not data or ";base64" not in header:
            return None
        media_type = header[5:].split(";", 1)[0] or "image/jpeg"
        return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}
    if url.startswith(("https://", "http://")):
        return {"type": "image", "source": {"type": "url", "url": url}}
    return None


def to_claude_turn(messages: list[dict], preamble: str) -> tuple[str, list[dict]]:
    """Fold Studio's chat history into a system prompt and one user turn.

    The Agent SDK takes user turns only, so earlier assistant replies ride in
    the transcript, the way the Cursor provider sends them.
    """
    system = [preamble]
    lines: list[str] = []
    images: list[dict] = []
    for msg in messages:
        role = str(msg.get("role") or "user")
        content = msg.get("content")
        texts: list[str] = []
        if isinstance(content, str):
            texts.append(content.strip())
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    texts.append(str(part.get("text") or "").strip())
                elif part.get("type") == "image_url":
                    image_url = part.get("image_url")
                    url = image_url.get("url") if isinstance(image_url, dict) else image_url
                    block = _image_block(str(url or ""))
                    if block is not None:
                        images.append(block)
        text = "\n".join(piece for piece in texts if piece)
        if not text:
            continue
        if role == "system":
            system.append(text)
        else:
            lines.append(f"{role.upper()}:\n{text}")
    blocks: list[dict] = [*images, {"type": "text", "text": "\n\n".join(lines) or "Continue."}]
    return "\n\n".join(system), blocks


async def _single_turn(blocks: list[dict]):
    yield {
        "type": "user",
        "message": {"role": "user", "content": blocks},
        "parent_tool_use_id": None,
        "session_id": "default",
    }


def _signed_out(text: str) -> bool:
    lowered = text.lower()
    return "not logged in" in lowered or "/login" in lowered or "invalid api key" in lowered


def _isolated_options(**kwargs):
    """Agent SDK options that run on the seller's login only: none of their
    Claude Code settings, hooks, MCP servers or IDE hookups."""
    from claude_agent_sdk import ClaudeAgentOptions

    cli = claude_auth.claude_cli_path()
    if not cli:
        raise RuntimeError(
            f"Claude Code is not installed. Install it with: {claude_auth.INSTALL_COMMAND}"
        )
    return ClaudeAgentOptions(
        cli_path=cli,
        cwd=str(listing_scratch_dir()),
        setting_sources=[],
        settings=json.dumps({"disableAllHooks": True}),
        strict_mcp_config=True,
        env={
            "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
            "CLAUDE_CODE_AUTO_CONNECT_IDE": "0",
            "CLAUDE_CODE_IDE_SKIP_AUTO_INSTALL": "1",
        },
        **kwargs,
    )


async def list_models() -> list[dict]:
    """The models this Claude account offers, as Claude Code lists them in /model:
    ``[{"value", "label", "efforts"}]``."""
    from claude_agent_sdk import ClaudeSDKClient

    async with ClaudeSDKClient(_isolated_options(tools=[])) as client:
        info = await client.get_server_info() or {}
    models: list[dict] = []
    for item in info.get("models") or []:
        if not isinstance(item, dict) or not isinstance(item.get("value"), str):
            continue
        efforts = item.get("supportedEffortLevels") if item.get("supportsEffort") else None
        models.append(
            {
                "value": item["value"],
                "label": str(item.get("displayName") or item["value"]),
                "efforts": [str(level) for level in efforts or []],
            }
        )
    return models


class ClaudeProvider:
    name = "claude"

    def __init__(self):
        self.vision_model, self.listing_model = resolved_claude_models()
        self.effort = get_claude_models().get("effort")

    async def test_connection(self) -> bool:
        text = ""
        async for chunk in self._run(
            [{"role": "user", "content": "Reply with the single word OK."}],
            model=self.listing_model,
        ):
            kind, piece = unpack_stream_item(chunk)
            if kind == "content":
                text += piece
        if not text.strip():
            raise RuntimeError("Claude returned an empty reply.")
        return True

    async def analyze_photos(
        self,
        photo_paths: list[str],
        notes: str = "",
        listing_rules: str = "",
        max_side: int | None = VISION_MAX_SIDE,
    ) -> dict:
        system = (
            "You are a product listing analyst. Examine these product photos and extract "
            "structured evidence about the item. Separate visible facts from inference.\n\n"
            "Return ONLY valid JSON with these fields:\n"
            '- brand: {value, confidence, evidence}\n'
            "- size: {value, source: 'tag'|'measurement-derived'|'unreadable', confidence}\n"
            "- color: {value, confidence}\n"
            "- material: {value, confidence}\n"
            "- style: {value, confidence}\n"
            "- graphic: {value, confidence} — the named character, franchise, band, "
            "team, show or logo printed on the item (e.g. 'Snoopy and Woodstock'), "
            "empty when there is none. Generic prints belong in style, not here.\n"
            "- condition: {value, visibleFlaws: []}\n"
            "- measurements: [{label, value, source}]\n"
            "- category: {value, confidence}\n"
            "- department: {value, confidence} — who the item is cut for: "
            "Women, Men, Girls, Boys, Baby, or Unisex. Category trees split on "
            "this first, so infer it from cut, styling and sizing when no label "
            "says it.\n"
            "- uncertainties: [{field, issue}]\n"
            "- tag_text: {brand_label, size_tag, care_tag, rn_number} copied verbatim from any "
            "visible labels, empty strings when not visible\n\n"
            "Be conservative. Flag uncertainty. Do not invent details."
        )
        if notes:
            system += f"\n\nUser notes: {notes}"
        if listing_rules:
            system += f"\n\nAdditional rules:\n{listing_rules}"

        content_parts: list[dict] = [{"type": "text", "text": "Analyze these product photos:"}]
        for url in await encode_images(photo_paths[:10], max_side):
            content_parts.append({"type": "image_url", "image_url": {"url": url}})
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": content_parts},
        ]
        try:
            content = ""
            async for chunk in self._run(messages, model=self.vision_model):
                kind, piece = unpack_stream_item(chunk)
                if kind == "thinking":
                    live_trace.emit("thinking", piece)
                else:
                    content += piece
            if not content:
                raise RuntimeError("Claude returned an empty listing response")
            return self._parse_json_response(content)
        except Exception as e:
            return {"error": str(e), "evidence": {}}

    async def vision_chat(self, messages: list[dict]):
        async for chunk in self._run(messages, model=self.vision_model):
            yield chunk

    async def chat(self, messages: list[dict], stream: bool = True):
        if stream:
            async for chunk in self._run(messages, model=self.listing_model):
                yield chunk
            return
        text = ""
        async for chunk in self._run(messages, model=self.listing_model):
            kind, piece = unpack_stream_item(chunk)
            if kind == "content":
                text += piece
        if not text:
            raise RuntimeError("Claude returned an empty listing response")
        yield text

    async def web_search(self, messages: list[dict]) -> dict:
        """Run ``messages`` with web search and fetch only: ``{"answer", "sources"}``."""
        answer = ""
        async for chunk in self._run(
            messages,
            model=self.listing_model,
            tools=WEB_TOOLS,
            preamble=WEB_SEARCH_PREAMBLE,
            max_turns=WEB_SEARCH_MAX_TURNS,
        ):
            kind, piece = unpack_stream_item(chunk)
            if kind == "content":
                answer += piece
        return {"answer": answer.strip(), "sources": []}

    async def _run(
        self,
        messages: list[dict],
        *,
        model: str,
        tools: list[str] | None = None,
        preamble: str = TEXT_ONLY_PREAMBLE,
        max_turns: int = 1,
    ):
        """Stream one answer as StreamChunks.

        With tools the text between searches is narration, so only the final
        answer is yielded, once the run ends.
        """
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeSDKError,
            ResultMessage,
            StreamEvent,
            ToolUseBlock,
            query,
        )

        system, blocks = to_claude_turn(messages, preamble)
        options = _isolated_options(
            model=model,
            effort=self.effort,
            system_prompt=system,
            tools=list(tools or []),
            allowed_tools=list(tools or []),
            max_turns=max_turns,
            include_partial_messages=True,
        )
        stream_text = not tools
        streamed = False
        try:
            async for message in query(prompt=_single_turn(blocks), options=options):
                if isinstance(message, StreamEvent):
                    delta = message.event.get("delta") or {}
                    if message.event.get("type") != "content_block_delta":
                        continue
                    if delta.get("type") == "text_delta" and delta.get("text") and stream_text:
                        streamed = True
                        yield StreamChunk(delta["text"], "content")
                    elif delta.get("type") == "thinking_delta" and delta.get("thinking"):
                        yield StreamChunk(delta["thinking"], "thinking")
                elif isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, ToolUseBlock) and block.name == "WebSearch":
                            searched = str(block.input.get("query") or "")
                            if searched:
                                live_trace.emit("step", f"Claude searched: {searched}")
                elif isinstance(message, ResultMessage):
                    if message.is_error:
                        detail = (message.result or "").strip() or f"Claude run failed ({message.subtype})"
                        if _signed_out(detail):
                            claude_auth.forget_status()
                            raise RuntimeError(SIGNED_OUT)
                        raise RuntimeError(detail)
                    if not streamed and message.result:
                        yield StreamChunk(message.result, "content")
        except ClaudeSDKError as exc:
            detail = str(exc).strip()
            if _signed_out(detail):
                claude_auth.forget_status()
                raise RuntimeError(SIGNED_OUT) from exc
            raise RuntimeError(f"Claude error: {detail}") from exc

    def _parse_json_response(self, content: str) -> dict:
        try:
            return {"evidence": json.loads(content)}
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            try:
                return {"evidence": json.loads(match.group())}
            except json.JSONDecodeError:
                pass

        return {"evidence": {}, "raw": content}
