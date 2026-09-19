from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from vendoo_studio.config import user_data_root
from vendoo_studio.providers.xiaomi_mimo import VISION_MAX_SIDE, encode_images

log = logging.getLogger("vendoo_studio.cursor")

DEFAULT_MODEL = "composer-2.5"
TEXT_ONLY_PREAMBLE = (
    "You are a product listing assistant for Vendoo Listing Studio. "
    "Reply with assistant text only. Do not edit files, run shell commands, or use tools. "
    "When asked for JSON, return only valid JSON with no markdown fences."
)


def normalize_cursor_api_key(raw: str) -> str:
    key = raw.strip().strip('"').strip("'")
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key


def listing_scratch_dir() -> Path:
    path = user_data_root() / "cursor-listing-workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _image_from_data_url(url: str):
    from cursor_sdk import SDKImage

    if not url:
        return None
    if url.startswith("data:"):
        try:
            header, _, data = url.partition(",")
            mime = "image/jpeg"
            if ";" in header:
                mime = header[5:].split(";", 1)[0] or mime
            if not data:
                return None
            return SDKImage.data_image(data, mime)
        except Exception:
            log.warning("failed to parse data URL image for Cursor", exc_info=True)
            return None
    try:
        return SDKImage.from_url(url)
    except Exception:
        log.warning("failed to load image URL for Cursor", exc_info=True)
        return None


def _flatten_messages(messages: list[dict]) -> tuple[str, list]:
    lines = [TEXT_ONLY_PREAMBLE, ""]
    images: list = []
    for msg in messages:
        role = str(msg.get("role") or "user").upper()
        content = msg.get("content")
        if isinstance(content, str):
            text = content.strip()
            if text:
                lines.append(f"{role}:\n{text}")
            continue
        if not isinstance(content, list):
            continue
        texts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            kind = part.get("type")
            if kind == "text":
                piece = str(part.get("text") or "").strip()
                if piece:
                    texts.append(piece)
            elif kind == "image_url":
                image_url = part.get("image_url")
                url = ""
                if isinstance(image_url, dict):
                    url = str(image_url.get("url") or "")
                elif isinstance(image_url, str):
                    url = image_url
                image = _image_from_data_url(url)
                if image is not None:
                    images.append(image)
        if texts:
            lines.append(f"{role}:\n" + "\n".join(texts))
    return "\n\n".join(lines).strip(), images


class CursorProvider:
    name = "cursor"
    vision_model = DEFAULT_MODEL
    listing_model = DEFAULT_MODEL

    def __init__(self, api_key: str):
        self.api_key = normalize_cursor_api_key(api_key)

    async def test_connection(self) -> bool:
        """Validate the API key through the same local bridge path used for chat.

        Raises RuntimeError with a user-facing message on failure so Settings can
        show the real Cursor/SDK error instead of a generic "Connection failed".
        """
        from cursor_sdk import AsyncClient, CursorAgentError, CursorSDKError

        if not self.api_key:
            raise RuntimeError("Cursor API key is empty.")

        scratch = listing_scratch_dir()
        try:
            async with await AsyncClient.launch_bridge(workspace=str(scratch)) as client:
                models = await client.list_models(api_key=self.api_key)
        except CursorAgentError as exc:
            message = str(exc).strip() or "Cursor authentication failed."
            raise RuntimeError(message) from exc
        except CursorSDKError as exc:
            message = str(exc).strip() or "Cursor SDK is not available."
            raise RuntimeError(message) from exc
        except Exception as exc:
            log.warning("Cursor connection test failed", exc_info=True)
            raise RuntimeError(f"Cursor connection failed: {exc}") from exc

        if not models:
            raise RuntimeError("Cursor API key worked but returned no models for this account.")
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
            async for chunk in self._run(messages, stream=False):
                content += chunk
            return self._parse_json_response(content)
        except Exception as e:
            return {"error": str(e), "evidence": {}}

    async def vision_chat(self, messages: list[dict]):
        async for content in self._run(messages, stream=True):
            yield content

    async def chat(self, messages: list[dict], stream: bool = True):
        async for content in self._run(messages, stream=stream):
            yield content

    async def _run(self, messages: list[dict], *, stream: bool):
        from cursor_sdk import (
            AsyncClient,
            CursorAgentError,
            LocalAgentOptions,
            UserMessage,
        )

        prompt, images = _flatten_messages(messages)
        if not prompt:
            prompt = TEXT_ONLY_PREAMBLE
        scratch = listing_scratch_dir()
        message = UserMessage(text=prompt, images=images or None)

        try:
            async with await AsyncClient.launch_bridge(workspace=str(scratch)) as client:
                async with await client.agents.create(
                    model=self.listing_model,
                    api_key=self.api_key,
                    local=LocalAgentOptions(cwd=str(scratch), setting_sources=[]),
                ) as agent:
                    run = await agent.send(message)
                    if stream:
                        yielded = False
                        async for chunk in run.iter_text():
                            if chunk:
                                yielded = True
                                yield chunk
                        result = await run.wait()
                        if result.status == "error":
                            raise RuntimeError(f"Cursor run failed: {result.id}")
                        if not yielded and result.result:
                            yield result.result
                        return

                    result = await run.wait()
                    if result.status == "error":
                        raise RuntimeError(f"Cursor run failed: {result.id}")
                    text = (result.result or "").strip()
                    if not text:
                        raise RuntimeError("Cursor returned an empty listing response")
                    yield text
        except CursorAgentError as exc:
            raise RuntimeError(f"Cursor agent error: {exc}") from exc

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
