from __future__ import annotations

import asyncio
import base64
import json
from io import BytesIO
from typing import NamedTuple

import httpx
from PIL import Image, ImageOps

MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"


# Vision APIs downscale server-side (roughly 2000px long edge), so larger uploads only add latency.
VISION_MAX_SIDE = 1600
VISION_JPEG_QUALITY = 85


def _raw_data_url(path: str) -> str:
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    ext = path.rsplit(".", 1)[-1].lower()
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(ext, "jpeg")
    return f"data:image/{mime};base64,{data}"


def image_exceeds(path: str, max_side: int | None) -> bool:
    """True when the stored photo is larger than the vision encode limit."""
    if not max_side:
        return False
    try:
        with Image.open(path) as img:
            return max(img.size) > max_side
    except Exception:
        return False


def _encode_image(path: str, max_side: int | None = VISION_MAX_SIDE) -> str:
    """Data URL for a vision request; the stored original is never modified."""
    if not image_exceeds(path, max_side):
        return _raw_data_url(path)
    try:
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=VISION_JPEG_QUALITY, optimize=True)
    except Exception:
        return _raw_data_url(path)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")


async def encode_images(paths: list[str], max_side: int | None = VISION_MAX_SIDE) -> list[str]:
    """Encode photos off the event loop so resizing never stalls streaming responses."""
    return await asyncio.to_thread(lambda: [_encode_image(path, max_side) for path in paths])


def _error_message(payload: dict) -> str | None:
    error = payload.get("error")
    if error is None:
        return None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or error)
    return str(error)


class StreamChunk(NamedTuple):
    text: str
    kind: str = "content"


def unpack_stream_item(item) -> tuple[str, str]:
    if isinstance(item, StreamChunk):
        return item.kind, item.text
    if isinstance(item, str):
        return "content", item
    return "content", str(item)


def chunk_thinking(payload: dict) -> str:
    """Return reasoning tokens from a chat-completion payload."""
    choices = payload.get("choices") or []
    if not choices:
        return ""
    choice = choices[0] if isinstance(choices[0], dict) else {}
    for source in (choice.get("delta") or {}, choice.get("message") or {}):
        if not isinstance(source, dict):
            continue
        for key in ("reasoning_content", "reasoning"):
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def chunk_text(payload: dict) -> str:
    """Return visible assistant text from a chat-completion payload."""
    error = _error_message(payload)
    if error:
        raise RuntimeError(error)

    choices = payload.get("choices") or []
    if not choices:
        return ""
    choice = choices[0] if isinstance(choices[0], dict) else {}
    delta = choice.get("delta") or {}
    content = delta.get("content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("text") or "")
        return "".join(parts)
    if isinstance(content, str) and content:
        return content

    message = choice.get("message") or {}
    message_content = message.get("content")
    if isinstance(message_content, str):
        return message_content
    return ""


class MiMoProvider:
    name = "xiaomi-mimo"
    vision_model = "mimo-v2.5"
    listing_model = "mimo-v2.5-pro"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = MIMO_BASE_URL

    def _headers(self) -> dict[str, str]:
        return {
            "api-key": self.api_key,
            "Content-Type": "application/json",
        }

    async def test_connection(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.base_url}/models",
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def analyze_photos(
        self,
        photo_paths: list[str],
        notes: str = "",
        listing_rules: str = "",
        max_side: int | None = VISION_MAX_SIDE,
    ) -> dict:
        messages = [
            {
                "role": "system",
                "content": (
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
                    "- department: {value, confidence} — who the item is cut for: "
                    "Women, Men, Girls, Boys, Baby, or Unisex. Category trees split on this "
                    "first, so infer it from cut, styling and sizing when no label says it.\n"
                    "- uncertainties: [{field, issue}]\n"
                    "- tag_text: {brand_label, size_tag, care_tag, rn_number} copied verbatim from any "
                    "visible labels, empty strings when not visible\n\n"
                    "Be conservative. Flag uncertainty. Do not invent details."
                ),
            },
        ]

        if notes:
            messages[0]["content"] += f"\n\nUser notes: {notes}"

        if listing_rules:
            messages[0]["content"] += f"\n\nAdditional rules:\n{listing_rules}"

        content_parts = [{"type": "text", "text": "Analyze these product photos:"}]
        for url in await encode_images(photo_paths[:10], max_side):
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": url},
            })

        messages.append({"role": "user", "content": content_parts})

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json={
                        "model": "mimo-v2.5",
                        "messages": messages,
                        "max_tokens": 4096,
                        "temperature": 0.3,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return self._parse_json_response(content)
        except Exception as e:
            return {"error": str(e), "evidence": {}}

    async def chat(
        self,
        messages: list[dict],
        stream: bool = True,
    ):
        if stream:
            yielded = False
            try:
                async for content in self._stream_chat(messages):
                    if content:
                        yielded = True
                        yield content
            except Exception:
                if yielded:
                    raise
                async for content in self._complete_chat(messages):
                    yield content
                return
            if not yielded:
                async for content in self._complete_chat(messages):
                    yield content
            return

        async for content in self._complete_chat(messages):
            yield content

    async def quick_chat(self, messages: list[dict]):
        """Mechanical rewrites (JSON repair): thinking off so temperature applies and replies come fast."""
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={
                    "model": self.listing_model,
                    "messages": messages,
                    "max_tokens": 8192,
                    "temperature": 0.2,
                    "thinking": {"type": "disabled"},
                },
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"MiMo HTTP {resp.status_code}: {resp.text[:500]}")
            text = chunk_text(resp.json())
            if not text:
                raise RuntimeError("MiMo returned an empty repair response")
            yield text

    async def _stream_chat(self, messages: list[dict]):
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={
                    "model": "mimo-v2.5-pro",
                    "messages": messages,
                    "max_tokens": 8192,
                    "temperature": 0.7,
                    "stream": True,
                },
            ) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    raise RuntimeError(f"MiMo HTTP {resp.status_code}: {resp.text[:500]}")
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                    else:
                        data_str = line.strip()
                    if not data_str or data_str == "[DONE]":
                        if data_str == "[DONE]":
                            break
                        continue
                    try:
                        payload = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    thinking = chunk_thinking(payload)
                    if thinking:
                        yield StreamChunk(thinking, "thinking")
                    text = chunk_text(payload)
                    if text:
                        yield StreamChunk(text, "content")

    async def vision_chat(self, messages: list[dict]):
        """Chat whose user turns carry photos; the pro listing model is text-only."""
        async for content in self._complete_chat(messages, model=self.vision_model):
            yield content

    async def _complete_chat(self, messages: list[dict], model: str = "mimo-v2.5-pro"):
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": 8192,
                    "temperature": 0.7,
                },
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"MiMo HTTP {resp.status_code}: {resp.text[:500]}")
            data = resp.json()
            text = chunk_text(data)
            if not text:
                raise RuntimeError("MiMo returned an empty listing response")
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
