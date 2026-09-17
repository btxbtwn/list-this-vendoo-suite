"""Request/response calls to the interactive Vendoo browser in Chrome.

Studio shows a Vendoo draft tab as a live frame. These helpers send
``browser.*`` messages over the extension WebSocket and wait for the matching
``browser.result``. Pointer and keyboard input is fire-and-forget.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from vendoo_studio.models.protocol import ProtocolMessage

OPEN_TIMEOUT_SEC = 60.0
READ_TIMEOUT_SEC = 20.0
ACT_TIMEOUT_SEC = 30.0


class BrowserBridgeError(RuntimeError):
    pass


def _manager():
    from vendoo_studio.routes.extension import extension_manager

    return extension_manager


def _require_draft(job) -> None:
    from vendoo_studio.routes.extension import durable_vendoo_item_id

    if not durable_vendoo_item_id(job.vendoo_item_id) and not job.vendoo_url:
        raise BrowserBridgeError("Send the listing to Vendoo first so there is a draft to open.")


async def request(job, message_type: str, payload: dict[str, Any] | None = None, *, timeout: float = READ_TIMEOUT_SEC) -> dict:
    manager = _manager()
    if not manager.connected:
        raise BrowserBridgeError("Connect Chrome to use the Vendoo browser.")
    request_id = uuid.uuid4().hex
    waiter = manager.register_wait(request_id)
    sent = await manager.send_message(ProtocolMessage(
        type=message_type,
        job_id=job.id,
        message_id=request_id,
        payload={**(payload or {}), "job_id": job.id, "request_id": request_id},
    ).model_dump(mode="json"))
    if not sent:
        manager.cancel_wait(request_id)
        raise BrowserBridgeError("Could not reach the Chrome extension.")
    try:
        result = await asyncio.wait_for(waiter, timeout)
    except TimeoutError as exc:
        manager.cancel_wait(request_id)
        raise BrowserBridgeError("Chrome did not answer in time.") from exc
    return result if isinstance(result, dict) else {"ok": False, "error": "Malformed browser reply"}


async def open_session(job, marketplace: str | None = None) -> dict:
    from vendoo_studio.routes.extension import durable_vendoo_item_id

    _require_draft(job)
    return await request(job, "browser.open", {
        "vendoo_item_id": durable_vendoo_item_id(job.vendoo_item_id),
        "vendoo_url": job.vendoo_url,
        "marketplace": marketplace or "",
    }, timeout=OPEN_TIMEOUT_SEC)


async def close_session(job) -> dict:
    return await request(job, "browser.close", timeout=READ_TIMEOUT_SEC)


_TAKEOVER_MOUSE = frozenset({"mousePressed", "mouseWheel"})
_last_human_input: dict[str, float] = {}


def _is_takeover(event: dict) -> bool:
    # Hovering over the pane is not taking control; pressing, scrolling, or typing is.
    return event.get("kind") in {"key", "text"} or event.get("type") in _TAKEOVER_MOUSE


def human_input_since(job_id: str, since: float) -> bool:
    return _last_human_input.get(job_id, 0.0) > since


async def send_input(job, events: list[dict]) -> bool:
    if any(_is_takeover(event) for event in events):
        _last_human_input[job.id] = time.monotonic()
    manager = _manager()
    if not manager.connected:
        return False
    return await manager.send_message(ProtocolMessage(
        type="browser.input",
        job_id=job.id,
        payload={"job_id": job.id, "events": events},
    ).model_dump(mode="json"))


async def pick(job, x_ratio: float, y_ratio: float) -> dict:
    return await request(job, "browser.pick", {"x_ratio": x_ratio, "y_ratio": y_ratio})


async def snapshot(job) -> dict:
    return await request(job, "browser.snapshot")


async def act(job, action: dict) -> dict:
    return await request(job, "browser.act", action, timeout=ACT_TIMEOUT_SEC)
