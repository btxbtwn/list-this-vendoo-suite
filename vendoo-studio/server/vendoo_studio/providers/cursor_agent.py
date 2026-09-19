from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
from collections.abc import Iterator, Mapping
from pathlib import Path

from vendoo_studio.config import user_data_root
from vendoo_studio.providers.xiaomi_mimo import VISION_MAX_SIDE, encode_images
from vendoo_studio.services.user_settings import (
    DEFAULT_CURSOR_MODEL,
    resolved_cursor_models,
)

log = logging.getLogger("vendoo_studio.cursor")

DEFAULT_MODEL = DEFAULT_CURSOR_MODEL
TEXT_ONLY_PREAMBLE = (
    "You are a product listing assistant for Vendoo Listing Studio. "
    "Reply with assistant text only. Do not edit files, run shell commands, or use tools. "
    "When asked for JSON, return only valid JSON with no markdown fences."
)
_STREAM_DONE = object()


def normalize_cursor_api_key(raw: str) -> str:
    key = raw.strip().strip('"').strip("'")
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key


def listing_scratch_dir() -> Path:
    path = user_data_root() / "cursor-listing-workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


def uvloop_safe_subprocess_env(source: Mapping[str, object] | None = None) -> dict[str, str]:
    """Coerce bridge subprocess env to str values uvloop will accept.

    Studio runs uvicorn under uvloop. AsyncBridge passes this mapping to
    asyncio.create_subprocess_exec, which rejects PathLike/None/int values that
    subprocess.Popen would otherwise accept.
    """
    raw = dict(os.environ if source is None else source)
    cleaned: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(key, bytes):
            key_s = key.decode("utf-8", "surrogateescape")
        elif isinstance(key, str):
            key_s = key
        else:
            log.warning("dropping non-string Cursor bridge env key %r", key)
            continue
        if isinstance(value, str):
            cleaned[key_s] = value
        elif isinstance(value, bytes):
            cleaned[key_s] = value.decode("utf-8", "surrogateescape")
        elif value is None:
            log.warning("dropping null Cursor bridge env %s", key_s)
            continue
        else:
            coerced = os.fspath(value) if isinstance(value, os.PathLike) else str(value)
            log.warning(
                "coercing Cursor bridge env %s from %s",
                key_s,
                type(value).__name__,
            )
            cleaned[key_s] = coerced
    return cleaned


@contextlib.contextmanager
def _patched_bridge_env() -> Iterator[None]:
    import cursor_sdk._bridge as bridge_mod

    original = bridge_mod._bridge_subprocess_env

    def _safe() -> dict[str, str]:
        return uvloop_safe_subprocess_env(original())

    bridge_mod._bridge_subprocess_env = _safe
    try:
        yield
    finally:
        bridge_mod._bridge_subprocess_env = original


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

    def __init__(self, api_key: str):
        self.api_key = normalize_cursor_api_key(api_key)
        self.vision_model, self.listing_model = resolved_cursor_models()

    async def test_connection(self) -> bool:
        """Validate the API key through the same local bridge path used for chat.

        Raises RuntimeError with a user-facing message on failure so Settings can
        show the real Cursor/SDK error instead of a generic "Connection failed".
        """
        from cursor_sdk import Client, CursorAgentError, CursorSDKError

        if not self.api_key:
            raise RuntimeError("Cursor API key is empty.")

        scratch = str(listing_scratch_dir())

        def _probe() -> list:
            with _patched_bridge_env():
                with Client.launch_bridge(workspace=scratch) as client:
                    return list(client.list_models(api_key=self.api_key))

        try:
            # Sync bridge uses subprocess.Popen, which tolerates PathLike env
            # values that uvloop's create_subprocess_exec rejects.
            models = await asyncio.to_thread(_probe)
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

    def list_model_ids(self) -> list[str]:
        """Return catalog model IDs for Settings (sync; call from a worker thread)."""
        from cursor_sdk import Client

        scratch = str(listing_scratch_dir())
        with _patched_bridge_env():
            with Client.launch_bridge(workspace=scratch) as client:
                models = list(client.list_models(api_key=self.api_key))
        ids: list[str] = []
        for item in models:
            model_id = getattr(item, "id", None)
            if model_id is None and isinstance(item, dict):
                model_id = item.get("id")
            if isinstance(model_id, str) and model_id.strip():
                ids.append(model_id.strip())
        return ids

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
            async for chunk in self._run(messages, stream=False, model=self.vision_model):
                content += chunk
            return self._parse_json_response(content)
        except Exception as e:
            return {"error": str(e), "evidence": {}}

    async def vision_chat(self, messages: list[dict]):
        async for content in self._run(messages, stream=True, model=self.vision_model):
            yield content

    async def chat(self, messages: list[dict], stream: bool = True):
        async for content in self._run(messages, stream=stream, model=self.listing_model):
            yield content

    async def _run(self, messages: list[dict], *, stream: bool, model: str | None = None):
        from cursor_sdk import (
            Client,
            CursorAgentError,
            LocalAgentOptions,
            UserMessage,
        )

        selected = (model or self.listing_model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
        prompt, images = _flatten_messages(messages)
        if not prompt:
            prompt = TEXT_ONLY_PREAMBLE
        scratch = str(listing_scratch_dir())
        message = UserMessage(text=prompt, images=images or None)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[object] = asyncio.Queue()

        def _emit(item: object) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, item)

        def _worker() -> None:
            try:
                with _patched_bridge_env():
                    with Client.launch_bridge(workspace=scratch) as client:
                        with client.agents.create(
                            model=selected,
                            api_key=self.api_key,
                            local=LocalAgentOptions(cwd=scratch, setting_sources=[]),
                        ) as agent:
                            run = agent.send(message)
                            if stream:
                                yielded = False
                                for chunk in run.iter_text():
                                    if chunk:
                                        yielded = True
                                        _emit(chunk)
                                result = run.wait()
                                if result.status == "error":
                                    raise RuntimeError(f"Cursor run failed: {result.id}")
                                if not yielded and result.result:
                                    _emit(result.result)
                                return

                            result = run.wait()
                            if result.status == "error":
                                raise RuntimeError(f"Cursor run failed: {result.id}")
                            text = (result.result or "").strip()
                            if not text:
                                raise RuntimeError("Cursor returned an empty listing response")
                            _emit(text)
            except CursorAgentError as exc:
                _emit(RuntimeError(f"Cursor agent error: {exc}"))
            except Exception as exc:
                _emit(exc)
            finally:
                _emit(_STREAM_DONE)

        worker_task = asyncio.create_task(asyncio.to_thread(_worker))
        try:
            while True:
                item = await queue.get()
                if item is _STREAM_DONE:
                    break
                if isinstance(item, BaseException):
                    raise item
                yield item  # type: ignore[misc]
        finally:
            await worker_task

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
