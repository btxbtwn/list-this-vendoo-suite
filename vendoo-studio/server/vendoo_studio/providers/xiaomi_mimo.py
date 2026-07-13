from __future__ import annotations

import base64
import httpx

MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"


def _encode_image(path: str) -> str:
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    ext = path.rsplit(".", 1)[-1].lower()
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(ext, "jpeg")
    return f"data:image/{mime};base64,{data}"


class MiMoProvider:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = MIMO_BASE_URL

    async def test_connection(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.base_url}/models",
                    headers={
                        "api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
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
                    headers={
                        "api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
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
        async with httpx.AsyncClient(timeout=300) as client:
            if stream:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers={
                        "api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "mimo-v2.5-pro",
                        "messages": messages,
                        "max_tokens": 8192,
                        "temperature": 0.7,
                        "stream": True,
                    },
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            import json
                            try:
                                chunk = json.loads(data_str)
                                delta = chunk["choices"][0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except (json.JSONDecodeError, KeyError, IndexError):
                                continue
            else:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "mimo-v2.5-pro",
                        "messages": messages,
                        "max_tokens": 8192,
                        "temperature": 0.7,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                yield data["choices"][0]["message"]["content"]

    def _parse_json_response(self, content: str) -> dict:
        import json
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
