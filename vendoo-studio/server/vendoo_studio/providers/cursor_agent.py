from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import threading
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from vendoo_studio.config import user_data_root
from vendoo_studio.services import live_trace
from vendoo_studio.providers.xiaomi_mimo import VISION_MAX_SIDE, encode_images
from vendoo_studio.services.user_settings import (
    DEFAULT_CURSOR_MODEL,
    get_cursor_reasoning,
    resolved_cursor_models,
)

log = logging.getLogger("vendoo_studio.cursor")

DEFAULT_MODEL = DEFAULT_CURSOR_MODEL
TEXT_ONLY_PREAMBLE = (
    "You are a product listing assistant for Vendoo Listing Studio. "
    "Reply with assistant text only. Do not edit files, run shell commands, or use tools. "
    "When asked for JSON, return only valid JSON with no markdown fences."
)
WEB_SEARCH_PREAMBLE = (
    "You are a research assistant for Vendoo Listing Studio. Use only web search and "
    "web fetch. Do not edit files or run shell commands. "
    "When asked for JSON, return only valid JSON with no markdown fences."
)
# The only built-in tools a comps search may use.
WEB_TOOLS = ("webSearch", "webFetch")
# Cursor keeps searching well past any budget the prompt asks for, and a run
# stopped from outside returns nothing. So the search is stopped here and the
# same agent, which remembers what it found, is asked to answer at once.
# Leaves room inside comp_research's MODEL_SEARCH_TIMEOUT_SEC for that answer.
WEB_SEARCH_WRAP_UP_SEC = 55.0
WEB_SEARCH_WRAP_UP = (
    "Stop searching now. Reply immediately with the JSON of every sold comp and live "
    "listing you have already found, in the required shape. Do not search again."
)
# Cursor models name their reasoning knob differently ("reasoning", "effort",
# "thinking"); the first parameter matching one of these is the one Studio sets.
REASONING_PARAM_PATTERN = re.compile(r"reasoning|effort|thinking", re.IGNORECASE)
_STREAM_DONE = object()
# A Cursor run that sends nothing for this long has stalled. The SDK waits on
# it forever, and generation's field fill sat behind one with the listing busy.
IDLE_TIMEOUT_SEC = 300.0
# How long a stopped run's worker gets to exit. Cancel and close normally free it
# at once, but a run that went quiet after its answer ignored both and held the
# listing busy for good, so past this the worker is left behind instead.
WORKER_EXIT_GRACE_SEC = 10.0


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


def reasoning_parameter(model) -> object | None:
    """The model's reasoning parameter definition, or None when it has none."""
    for param in getattr(model, "parameters", ()) or ():
        label = f"{getattr(param, 'id', '')} {getattr(param, 'display_name', '')}"
        if REASONING_PARAM_PATTERN.search(label) and getattr(param, "values", ()):
            return param
    return None


def default_param_value(model, param_id: str) -> str | None:
    """The value the model's default variant uses for ``param_id``."""
    for variant in getattr(model, "variants", ()) or ():
        if not getattr(variant, "is_default", False):
            continue
        for param in getattr(variant, "params", ()) or ():
            if getattr(param, "id", None) == param_id:
                return getattr(param, "value", None)
    return None


def model_selection(model: str) -> str | dict:
    """``model`` with the saved reasoning level when it was chosen for this model."""
    reasoning = get_cursor_reasoning()
    if not reasoning or reasoning["model"] != model:
        return model
    return {"id": model, "params": [{"id": reasoning["param"], "value": reasoning["value"]}]}


@dataclass(frozen=True)
class _Thinking:
    text: str
    finished: bool


def _flatten_messages(messages: list[dict], preamble: str = TEXT_ONLY_PREAMBLE) -> tuple[str, list]:
    lines = [preamble, ""]
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

    def list_models(self) -> list:
        """Return the account's model catalog for Settings (sync; call from a worker thread)."""
        from cursor_sdk import Client

        scratch = str(listing_scratch_dir())
        with _patched_bridge_env():
            with Client.launch_bridge(workspace=scratch) as client:
                models = list(client.list_models(api_key=self.api_key))
        return [item for item in models if isinstance(getattr(item, "id", None), str) and item.id.strip()]

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

    async def web_search(self, messages: list[dict]) -> dict:
        """Run ``messages`` with web search and fetch only: ``{"answer", "sources"}``.

        The SDK does not report web tool calls, so each finished thought
        ("Searching Mercari for sold …") is what shows the search moving.
        """
        thought = ""

        def on_thinking(piece: _Thinking) -> None:
            nonlocal thought
            thought += piece.text
            if piece.finished:
                line = " ".join(thought.split())
                thought = ""
                if line:
                    live_trace.emit("step", f"Cursor: {line[:200]}")

        answer = ""
        async for chunk in self._run(
            messages,
            stream=False,
            model=self.listing_model,
            tools=WEB_TOOLS,
            on_thinking=on_thinking,
            preamble=WEB_SEARCH_PREAMBLE,
            wrap_up=(WEB_SEARCH_WRAP_UP_SEC, WEB_SEARCH_WRAP_UP),
        ):
            answer += chunk
        return {"answer": answer.strip(), "sources": []}

    async def _run(
        self,
        messages: list[dict],
        *,
        stream: bool,
        model: str | None = None,
        tools: tuple[str, ...] | None = None,
        on_thinking: Callable[[_Thinking], None] | None = None,
        wrap_up: tuple[float, str] | None = None,
        preamble: str = TEXT_ONLY_PREAMBLE,
    ):
        from cursor_sdk import (
            Client,
            CursorAgentError,
            LocalAgentOptions,
            UserMessage,
        )

        selected = (model or self.listing_model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
        prompt, images = _flatten_messages(messages, preamble)
        if not prompt:
            prompt = preamble
        scratch = str(listing_scratch_dir())
        message = UserMessage(text=prompt, images=images or None)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[object] = asyncio.Queue()

        def _emit(item: object) -> None:
            # A worker left behind may outlive the loop it reports to.
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(queue.put_nowait, item)

        handles: dict[str, object] = {}

        def _worker() -> None:
            try:
                with _patched_bridge_env():
                    with Client.launch_bridge(workspace=scratch) as client:
                        handles["client"] = client
                        with client.agents.create(
                            {"tools": list(tools)} if tools is not None else None,
                            model=model_selection(selected),
                            api_key=self.api_key,
                            local=LocalAgentOptions(cwd=scratch, setting_sources=[]),
                        ) as agent:
                            def drain(run) -> bool:
                                """Relay thinking and (when streaming) text; True if text went out."""
                                yielded = False
                                if not stream and on_thinking is None:
                                    return yielded
                                for sdk_message in run.stream():
                                    kind = getattr(sdk_message, "type", "")
                                    if kind == "thinking" and on_thinking is not None:
                                        _emit(_Thinking(
                                            text=str(getattr(sdk_message, "text", "") or ""),
                                            finished=getattr(sdk_message, "thinking_duration_ms", None) is not None,
                                        ))
                                    elif kind == "assistant" and stream:
                                        content = getattr(getattr(sdk_message, "message", None), "content", ())
                                        for block in content:
                                            chunk = getattr(block, "text", "")
                                            if chunk:
                                                yielded = True
                                                _emit(chunk)
                                return yielded

                            run = agent.send(message)
                            handles["run"] = run
                            wrapped = threading.Event()
                            timer = None
                            if wrap_up is not None:
                                def _stop_searching() -> None:
                                    wrapped.set()
                                    with contextlib.suppress(Exception):
                                        run.cancel()

                                timer = threading.Timer(wrap_up[0], _stop_searching)
                                timer.daemon = True
                                timer.start()
                            try:
                                yielded = drain(run)
                                result = run.wait()
                            finally:
                                if timer is not None:
                                    timer.cancel()
                            if wrap_up is not None and wrapped.is_set() and result.status == "cancelled":
                                run = agent.send(UserMessage(text=wrap_up[1]))
                                handles["run"] = run
                                yielded = drain(run)
                                result = run.wait()
                            if result.status == "error":
                                raise RuntimeError(f"Cursor run failed: {result.id}")
                            if stream:
                                if not yielded and result.result:
                                    _emit(result.result)
                                return
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

        def _abort() -> None:
            # Cancelling the run and closing the bridge ends the worker's
            # blocking wait, so the thread exits instead of outliving the caller.
            run = handles.get("run")
            client = handles.get("client")
            with contextlib.suppress(Exception):
                if run is not None:
                    run.cancel()
            with contextlib.suppress(Exception):
                if client is not None:
                    client.close()

        worker_done = threading.Event()

        def _worker_thread() -> None:
            try:
                _worker()
            finally:
                worker_done.set()

        # A daemon thread, not the shared executor: a worker the SDK never frees
        # must not take an executor slot or hold up quitting the app.
        threading.Thread(target=_worker_thread, name="cursor-run", daemon=True).start()
        finished = False
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=IDLE_TIMEOUT_SEC)
                except TimeoutError:
                    raise RuntimeError(
                        f"Cursor stopped responding for {int(IDLE_TIMEOUT_SEC // 60)} minutes. Retry."
                    ) from None
                if item is _STREAM_DONE:
                    finished = True
                    break
                if isinstance(item, BaseException):
                    finished = True
                    raise item
                if isinstance(item, _Thinking):
                    if on_thinking is not None:
                        on_thinking(item)
                    continue
                yield item  # type: ignore[misc]
        finally:
            if not finished:
                threading.Thread(target=_abort, name="cursor-abort", daemon=True).start()
            if not await asyncio.to_thread(worker_done.wait, WORKER_EXIT_GRACE_SEC):
                log.warning("Cursor run did not stop after %.0fs; leaving its worker behind", WORKER_EXIT_GRACE_SEC)

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
