from __future__ import annotations

import base64
import json

import httpx

MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"


def _encode_image(path: str) -> str:
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    ext = path.rsplit(".", 1)[-1].lower()
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(ext, "jpeg")
    return f"data:image/{mime};base64,{data}"


def _error_message(payload: dict) -> str | None:
    error = payload.get("error")
    if error is None:
        return None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or error)
    return str(error)


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
                    "- uncertainties: [{field, issue}]\n\n"
                    "Be conservative. Flag uncertainty. Do not invent details."
                ),
            },
        ]

        if notes:
            messages[0]["content"] += f"\n\nUser notes: {notes}"

        if listing_rules:
            messages[0]["content"] += f"\n\nAdditional rules:\n{listing_rules}"

        content_parts = [{"type": "text", "text": "Analyze these product photos:"}]
        for path in photo_paths[:10]:
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": _encode_image(path)},
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
                    text = chunk_text(payload)
                    if text:
                        yield text

    async def _complete_chat(self, messages: list[dict]):
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={
                    "model": "mimo-v2.5-pro",
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
