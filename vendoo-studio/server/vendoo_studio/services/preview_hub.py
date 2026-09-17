from __future__ import annotations

import asyncio
from typing import Any, Optional


MAX_FRAME_CHARS = 1_500_000
ALLOWED_MIMES = {"image/jpeg"}


def sanitize_frame(payload: dict[str, Any], step: str = "") -> Optional[dict[str, Any]]:
    mime = payload.get("mime") or "image/jpeg"
    if mime not in ALLOWED_MIMES:
        return None

    data = payload.get("data") or ""
    if not isinstance(data, str) or not data or len(data) > MAX_FRAME_CHARS:
        return None

    url = payload.get("url") or ""
    if not isinstance(url, str) or not url.startswith("https://"):
        url = ""

    width = payload.get("width")
    height = payload.get("height")
    viewport_width = payload.get("viewport_width")
    viewport_height = payload.get("viewport_height")
    return {
        "mime": mime,
        "data": data,
        "url": url[:300],
        "step": step or (payload.get("step") or ""),
        "width": width if isinstance(width, int) else None,
        "height": height if isinstance(height, int) else None,
        "viewport_width": viewport_width if _dimension(viewport_width) else None,
        "viewport_height": viewport_height if _dimension(viewport_height) else None,
    }


def _dimension(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value <= 10_000


class PreviewHub:
    """In-memory latest-frame fan-out. Never persists or logs image bytes."""

    def __init__(self) -> None:
        self._latest: dict[str, dict[str, Any]] = {}
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, job_id: str, frame: dict[str, Any]) -> None:
        async with self._lock:
            # One automation job at a time — keep a single latest frame in memory.
            stale_ids = [key for key in self._latest if key != job_id]
            self._latest = {job_id: frame}
            queues = list(self._subscribers.get(job_id, ()))
            for stale_id in stale_ids:
                self._subscribers.pop(stale_id, None)

        for queue in queues:
            _replace_latest(queue, frame)

    async def subscribe(self, job_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        async with self._lock:
            self._subscribers.setdefault(job_id, set()).add(queue)
            latest = self._latest.get(job_id)
        if latest is not None:
            _replace_latest(queue, latest)
        return queue

    async def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(job_id)
            if not subscribers:
                return
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(job_id, None)

    def latest(self, job_id: str) -> Optional[dict[str, Any]]:
        return self._latest.get(job_id)

    async def clear(self, job_id: str) -> None:
        async with self._lock:
            self._latest.pop(job_id, None)
            self._subscribers.pop(job_id, None)


def _replace_latest(queue: asyncio.Queue, frame: dict[str, Any]) -> None:
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    try:
        queue.put_nowait(frame)
    except asyncio.QueueFull:
        pass


preview_hub = PreviewHub()
