from __future__ import annotations

import json
import time

import httpx

from vendoo_studio.providers.xiaomi_mimo import (
    VISION_MAX_SIDE,
    StreamChunk,
    chunk_text,
    encode_images,
    unpack_stream_item,
)
from vendoo_studio.services.chatgpt_oauth import (
    ORIGINATOR,
    account_id_from_tokens,
    refresh_chatgpt_tokens,
)
from vendoo_studio.services.keychain import get_chatgpt_models

CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
USER_AGENT = "VendooStudio/0.1.0"
MODELS_CLIENT_VERSION = "1.0.0"
VISION_MODEL = "gpt-5.5"
LISTING_MODEL = "gpt-5.5"
DEFAULT_REASONING_EFFORT = "low"
PROMPT_CACHE_KEY = "vendoo-studio-listing"
REASONING_LADDER = ("none", "low", "medium", "high", "xhigh", "max")
CATALOG_TTL_S = 60

_catalog_cached_at = 0.0
_catalog_slugs: list[str] = []


def resolved_chatgpt_models() -> tuple[str, str]:
    prefs = get_chatgpt_models()
    vision = prefs.get("vision_model") or VISION_MODEL
    listing = prefs.get("listing_model") or LISTING_MODEL
    return vision, listing


def resolved_chatgpt_reasoning() -> str:
    prefs = get_chatgpt_models()
    return prefs.get("reasoning_effort") or DEFAULT_REASONING_EFFORT


def supported_reasoning_efforts(model: str) -> tuple[str, ...]:
    slug = (model or "").strip().lower().rsplit("/", 1)[-1]
    if "astra" in slug:
        return ("low", "medium", "high", "xhigh", "max")
    if "gpt-5.6" in slug:
        return ("none", "low", "medium", "high", "xhigh", "max")
    return ("none", "low", "medium", "high", "xhigh")


def clamp_reasoning_effort(effort: str, model: str) -> str:
    supported = supported_reasoning_efforts(model)
    requested = (effort or "").strip().lower()
    if requested == "minimal":
        requested = "low"
    if requested in supported:
        return requested
    try:
        index = REASONING_LADDER.index(requested)
    except ValueError:
        return DEFAULT_REASONING_EFFORT if DEFAULT_REASONING_EFFORT in supported else supported[0]
    for candidate in reversed(REASONING_LADDER[:index]):
        if candidate in supported:
            return candidate
    return supported[0]


def visible_model_slugs(payload: object) -> list[str]:
    entries = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return []
    sortable: list[tuple[int, str]] = []
    seen: set[str] = set()
    for item in entries:
        if not isinstance(item, dict):
            continue
        slug = item.get("slug")
        if not isinstance(slug, str) or not slug.strip():
            continue
        slug = slug.strip()
        visibility = item.get("visibility")
        if isinstance(visibility, str) and visibility.strip().lower() in {"hide", "hidden"}:
            continue
        if slug in seen:
            continue
        seen.add(slug)
        priority = item.get("priority")
        rank = int(priority) if isinstance(priority, (int, float)) else 10_000
        sortable.append((rank, slug))
    sortable.sort()
    return [slug for _, slug in sortable]


def _http_error(resp: httpx.Response) -> str:
    text = (resp.text or "").strip()
    try:
        payload = resp.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            text = detail.strip()
        else:
            error = payload.get("error")
            if isinstance(error, dict):
                text = str(error.get("message") or error.get("code") or error)
            elif isinstance(error, str) and error:
                text = error
    text = " ".join(text.split())
    if len(text) > 240:
        text = text[:237] + "..."
    return f"ChatGPT HTTP {resp.status_code}: {text}" if text else f"ChatGPT HTTP {resp.status_code}"


def _delta_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        text = value.get("text") or value.get("content") or ""
        return text if isinstance(text, str) else ""
    return ""


def _responses_thinking(payload: dict) -> str:
    event_type = str(payload.get("type") or "")
    if any(marker in event_type for marker in (
        "reasoning_summary_text.delta",
        "reasoning_text.delta",
        "reasoning.delta",
    )):
        return _delta_text(payload.get("delta"))
    return ""


def _responses_text(payload: dict) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        raise RuntimeError(str(error.get("message") or error.get("code") or error))
    if isinstance(error, str) and error:
        raise RuntimeError(error)

    event_type = str(payload.get("type") or "")
    if event_type.endswith("output_text.delta") or event_type == "response.output_text.delta":
        delta = payload.get("delta")
        return delta if isinstance(delta, str) else ""

    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text:
        return output_text

    parts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text") or content.get("output_text")
            if isinstance(text, str):
                parts.append(text)
    if parts:
        return "".join(parts)

    try:
        return chunk_text(payload)
    except RuntimeError:
        raise
    except Exception:
        return ""


def _output_items(payload: dict) -> list[dict]:
    event_type = str(payload.get("type") or "")
    if event_type == "response.completed":
        response = payload.get("response")
        if isinstance(response, dict) and isinstance(response.get("output"), list):
            return [item for item in response["output"] if isinstance(item, dict)]
    if event_type.endswith("output_item.done"):
        item = payload.get("item")
        if isinstance(item, dict):
            return [item]
    output = payload.get("output")
    if isinstance(output, list):
        return [item for item in output if isinstance(item, dict)]
    return []


def web_search_answer(output: list[dict]) -> str:
    parts: list[str] = []
    for item in output:
        if item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text") or part.get("output_text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n".join(parts).strip()


def web_search_sources(output: list[dict]) -> list[dict]:
    sources: list[dict] = []
    seen: set[str] = set()

    def add(url: object, title: object, snippet: object = "") -> None:
        href = str(url or "").strip()
        if not href or href in seen:
            return
        seen.add(href)
        sources.append({
            "url": href,
            "title": str(title or "").strip(),
            "description": str(snippet or "").strip(),
        })

    for item in output:
        if item.get("type") == "message":
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                annotations = part.get("annotations")
                if not isinstance(annotations, list):
                    continue
                for annotation in annotations:
                    if not isinstance(annotation, dict):
                        continue
                    if annotation.get("type") != "url_citation":
                        continue
                    add(annotation.get("url"), annotation.get("title"))
            continue
        if item.get("type") != "web_search_call":
            continue
        action = item.get("action") if isinstance(item.get("action"), dict) else {}
        for group in (action.get("sources"), item.get("sources"), item.get("results")):
            if not isinstance(group, list):
                continue
            for source in group:
                if not isinstance(source, dict):
                    continue
                add(
                    source.get("url") or source.get("source_website_url"),
                    source.get("title") or source.get("caption"),
                    source.get("description") or source.get("snippet"),
                )
    return sources


def _content_type_for_role(role: str) -> str:
    return "output_text" if role in {"assistant", "model"} else "input_text"


def _messages_to_input(messages: list[dict]) -> tuple[str, list[dict]]:
    instructions: list[str] = []
    items: list[dict] = []
    for message in messages:
        role = message.get("role") or "user"
        content = message.get("content")
        if role == "system":
            if isinstance(content, str) and content.strip():
                instructions.append(content)
            continue
        mapped_role = "assistant" if role in {"assistant", "model"} else "user"
        text_type = _content_type_for_role(mapped_role)
        parts: list[dict] = []
        if isinstance(content, str):
            if content:
                parts.append({"type": text_type, "text": content})
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, str) and part:
                    parts.append({"type": text_type, "text": part})
                elif isinstance(part, dict):
                    if part.get("type") in {"text", "input_text", "output_text"} and part.get("text"):
                        parts.append({"type": text_type, "text": str(part["text"])})
                    elif mapped_role == "user" and part.get("type") == "image_url":
                        image = part.get("image_url") or {}
                        url = image.get("url") if isinstance(image, dict) else None
                        if url:
                            parts.append({"type": "input_image", "image_url": url})
        if not parts:
            continue
        items.append({"role": mapped_role, "content": parts, "type": "message"})
    return "\n\n".join(instructions), items


async def _codex_headers() -> dict[str, str]:
    tokens = await refresh_chatgpt_tokens()
    if not tokens:
        raise RuntimeError("Not signed in with ChatGPT")
    headers = {
        "Authorization": f"Bearer {tokens['access_token']}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": USER_AGENT,
        "originator": ORIGINATOR,
        "OpenAI-Beta": "responses=experimental",
    }
    account_id = account_id_from_tokens(tokens)
    if account_id:
        headers["ChatGPT-Account-ID"] = account_id
    return headers


async def fetch_codex_models(*, force: bool = False) -> list[str]:
    global _catalog_cached_at, _catalog_slugs
    now = time.time()
    if not force and _catalog_slugs and now - _catalog_cached_at < CATALOG_TTL_S:
        return list(_catalog_slugs)
    headers = await _codex_headers()
    headers.pop("Accept", None)
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"{CODEX_BASE_URL}/models",
            params={"client_version": MODELS_CLIENT_VERSION},
            headers=headers,
        )
    if resp.status_code >= 400:
        raise RuntimeError(_http_error(resp))
    slugs = visible_model_slugs(resp.json())
    _catalog_slugs = slugs
    _catalog_cached_at = now
    return list(slugs)


class ChatGPTCodexProvider:
    name = "chatgpt"
    base_url = CODEX_BASE_URL

    def __init__(self):
        self.vision_model, self.listing_model = resolved_chatgpt_models()
        self.reasoning_effort = resolved_chatgpt_reasoning()

    async def _headers(self) -> dict[str, str]:
        return await _codex_headers()

    async def test_connection(self) -> bool:
        await fetch_codex_models(force=True)
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
            "- condition: {value, visibleFlaws: []}\n"
            "- measurements: [{label, value, source}]\n"
            "- category: {value, confidence}\n"
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
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": url},
            })
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": content_parts},
        ]
        try:
            content = ""
            async for chunk in self._complete(messages, model=self.vision_model):
                content += chunk
            return self._parse_json_response(content)
        except Exception as e:
            return {"error": str(e), "evidence": {}}

    async def vision_chat(self, messages: list[dict]):
        """Chat whose user turns carry photos."""
        async for content in self._complete(messages, model=self.vision_model):
            yield content

    async def chat(self, messages: list[dict], stream: bool = True):
        if stream:
            yielded = False
            try:
                async for content in self._stream(messages, model=self.listing_model):
                    if content:
                        yielded = True
                        yield content
            except Exception:
                if yielded:
                    raise
                async for content in self._complete(messages, model=self.listing_model):
                    yield content
                return
            if not yielded:
                async for content in self._complete(messages, model=self.listing_model):
                    yield content
            return
        async for content in self._complete(messages, model=self.listing_model):
            yield content

    def _payload(
        self,
        messages: list[dict],
        model: str,
        stream: bool,
        *,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        include: list[str] | None = None,
        reasoning_effort: str | None = None,
    ) -> dict:
        instructions, items = _messages_to_input(messages)
        effort = clamp_reasoning_effort(reasoning_effort or self.reasoning_effort, model)
        payload: dict = {
            "model": model,
            "input": items or [{"role": "user", "content": [{"type": "input_text", "text": "Continue."}], "type": "message"}],
            "store": False,
            "stream": stream,
            "reasoning": {"effort": effort},
            # Shared key routes requests to warm prefix caches; prompts put static rules first.
            "prompt_cache_key": PROMPT_CACHE_KEY,
        }
        if payload["reasoning"]["effort"] != "none":
            payload["reasoning"]["summary"] = "auto"
        if instructions:
            payload["instructions"] = instructions
        if tools:
            payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice
        if include:
            payload["include"] = include
        return payload

    async def _stream(self, messages: list[dict], model: str, **payload_kwargs):
        headers = await self._headers()
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/responses",
                headers=headers,
                json=self._payload(messages, model, True, **payload_kwargs),
            ) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    raise RuntimeError(_http_error(resp))
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    data_str = line[5:].strip() if line.startswith("data:") else line.strip()
                    if not data_str or data_str == "[DONE]":
                        if data_str == "[DONE]":
                            break
                        continue
                    try:
                        payload = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    thinking = _responses_thinking(payload)
                    if thinking:
                        yield StreamChunk(thinking, "thinking")
                    text = _responses_text(payload)
                    if text:
                        yield StreamChunk(text, "content")

    async def quick_chat(self, messages: list[dict]):
        """Mechanical rewrites (JSON repair) need no reasoning budget."""
        text = ""
        async for chunk in self._stream(messages, self.listing_model, reasoning_effort="none"):
            kind, piece = unpack_stream_item(chunk)
            if kind == "content":
                text += piece
        if not text:
            raise RuntimeError("ChatGPT returned an empty repair response")
        yield text

    async def _complete(self, messages: list[dict], model: str):
        text = ""
        async for chunk in self._stream(messages, model):
            kind, piece = unpack_stream_item(chunk)
            if kind != "thinking":
                text += piece
        if not text:
            raise RuntimeError("ChatGPT returned an empty listing response")
        yield text

    async def web_search(self, query: str) -> dict:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are researching sold prices for a secondhand marketplace listing. "
                    "Search the live web for recently sold comps on eBay, Poshmark, Mercari, Depop, and Etsy. "
                    "Keep only specific sold items with a real sold price. Ignore how-to articles, "
                    "search pages, Terapeak marketing, and pricing guides. "
                    "Return JSON only in this shape: "
                    '{"market":"$18-$25","comps":[{"title":"...","price":22,"marketplace":"eBay",'
                    '"condition":"Good","url":"https://www.ebay.com/itm/123"}]} '
                    "Prefer listing URLs (ebay.com/itm, poshmark.com/listing, mercari.com/us/item, "
                    "depop.com/products, etsy.com/listing). Do not write a listing. Do not invent "
                    "prices or URLs. If you cannot find sold comps, return {\"market\":\"\",\"comps\":[]}."
                ),
            },
            {"role": "user", "content": f"Find recently sold marketplace comps for: {query}"},
        ]
        errors: list[str] = []
        attempts = (
            {"external_web_access": True, "tool_choice": "required"},
            {"tool_choice": "required"},
        )
        for attempt in attempts:
            tool: dict = {"type": "web_search"}
            if attempt.get("external_web_access"):
                tool["external_web_access"] = True
            try:
                return await self._web_search_once(
                    messages,
                    tools=[tool],
                    tool_choice=str(attempt["tool_choice"]),
                )
            except Exception as exc:
                errors.append(str(exc))
        raise RuntimeError(errors[-1] if errors else "ChatGPT web search failed")

    async def _web_search_once(self, messages: list[dict], *, tools: list[dict], tool_choice: str) -> dict:
        answer = ""
        output: list[dict] = []
        async for chunk in self._stream_search(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            include=["web_search_call.action.sources"],
            reasoning_effort="low",
        ):
            kind, piece = unpack_stream_item(chunk)
            if kind == "content":
                answer += piece
            elif kind == "output":
                try:
                    items = json.loads(piece)
                except json.JSONDecodeError:
                    continue
                if isinstance(items, list):
                    output.extend(item for item in items if isinstance(item, dict))
        sources = web_search_sources(output)
        completed = web_search_answer(output)
        text = completed or answer.strip()
        if not text and not sources:
            raise RuntimeError("ChatGPT web search returned no results")
        return {"answer": text, "sources": sources}

    async def _stream_search(self, messages: list[dict], **payload_kwargs):
        headers = await self._headers()
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/responses",
                headers=headers,
                json=self._payload(messages, self.listing_model, True, **payload_kwargs),
            ) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    raise RuntimeError(_http_error(resp))
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    data_str = line[5:].strip() if line.startswith("data:") else line.strip()
                    if not data_str or data_str == "[DONE]":
                        if data_str == "[DONE]":
                            break
                        continue
                    try:
                        payload = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    text = _responses_text(payload)
                    if text:
                        yield StreamChunk(text, "content")
                    items = _output_items(payload)
                    if items:
                        yield StreamChunk(json.dumps(items), "output")

    def _parse_json_response(self, content: str) -> dict:
        import re

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
