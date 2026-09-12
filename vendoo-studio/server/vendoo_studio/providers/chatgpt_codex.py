from __future__ import annotations

import json
import time

import httpx

from vendoo_studio.providers.xiaomi_mimo import _encode_image, chunk_text
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
DEFAULT_REASONING_EFFORT = "medium"
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
        parts: list[dict] = []
        if isinstance(content, str):
            if content:
                parts.append({"type": "input_text", "text": content})
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, str) and part:
                    parts.append({"type": "input_text", "text": part})
                elif isinstance(part, dict):
                    if part.get("type") == "text" and part.get("text"):
                        parts.append({"type": "input_text", "text": str(part["text"])})
                    elif part.get("type") == "image_url":
                        image = part.get("image_url") or {}
                        url = image.get("url") if isinstance(image, dict) else None
                        if url:
                            parts.append({"type": "input_image", "image_url": url})
        if not parts:
            continue
        mapped_role = "assistant" if role in {"assistant", "model"} else "user"
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
            "- uncertainties: [{field, issue}]\n\n"
            "Be conservative. Flag uncertainty. Do not invent details."
        )
        if notes:
            system += f"\n\nUser notes: {notes}"
        if listing_rules:
            system += f"\n\nAdditional rules:\n{listing_rules}"

        content_parts: list[dict] = [{"type": "text", "text": "Analyze these product photos:"}]
        for path in photo_paths[:10]:
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": _encode_image(path)},
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

    def _payload(self, messages: list[dict], model: str, stream: bool) -> dict:
        instructions, items = _messages_to_input(messages)
        payload: dict = {
            "model": model,
            "input": items or [{"role": "user", "content": [{"type": "input_text", "text": "Continue."}], "type": "message"}],
            "store": False,
            "stream": stream,
            "reasoning": {"effort": clamp_reasoning_effort(self.reasoning_effort, model)},
        }
        if payload["reasoning"]["effort"] != "none":
            payload["reasoning"]["summary"] = "auto"
        if instructions:
            payload["instructions"] = instructions
        return payload

    async def _stream(self, messages: list[dict], model: str):
        headers = await self._headers()
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/responses",
                headers=headers,
                json=self._payload(messages, model, True),
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
                        yield text

    async def _complete(self, messages: list[dict], model: str):
        text = ""
        async for chunk in self._stream(messages, model):
            text += chunk
        if not text:
            raise RuntimeError("ChatGPT returned an empty listing response")
        yield text

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
