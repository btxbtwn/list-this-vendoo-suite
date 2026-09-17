"""Server-sent event helpers and resumable background listing-generation runs."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from fastapi.responses import StreamingResponse

from vendoo_studio.providers.xiaomi_mimo import unpack_stream_item

log = logging.getLogger("vendoo_studio.chat")

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}
KEEPALIVE = ": keepalive\n\n"
_DONE = object()
_generation_tasks: set[asyncio.Task] = set()
_generations: dict[str, GenerationRun] = {}


class GenerationRun:
    def __init__(self) -> None:
        self.history: list[str] = []
        self.subscribers: set[asyncio.Queue] = set()
        self.task: asyncio.Task | None = None
        self.done = False
        self.cancelling = False
        self.last_status = ""

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        for item in self.history:
            queue.put_nowait(item)
        if self.done:
            queue.put_nowait(_DONE)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.discard(queue)

    def publish(self, item: str, *, record: bool = True) -> None:
        if record and item != KEEPALIVE:
            self.history.append(item)
            if item.startswith("event: status\n"):
                for line in item.splitlines():
                    if line.startswith("data:"):
                        self.last_status = line[5:].lstrip()
                        break
        for queue in list(self.subscribers):
            queue.put_nowait(item)

    def pulse(self) -> None:
        """Keep mobile fetch/SSE alive with a comment and a status data frame.

        Comment-only keepalives are ignored by some mobile stacks, which then
        drop the connection during long category discovery waits.
        """
        self.publish(KEEPALIVE, record=False)
        if self.last_status:
            self.publish(sse_event("status", self.last_status), record=False)

    def finish(self) -> None:
        self.done = True
        for queue in list(self.subscribers):
            queue.put_nowait(_DONE)


def _forget_generation(conv_id: str, run: GenerationRun) -> None:
    if _generations.get(conv_id) is run:
        _generations.pop(conv_id, None)


def active_generation(conv_id: str) -> GenerationRun | None:
    run = _generations.get(conv_id)
    if run and not run.done and not run.cancelling:
        return run
    return None


def stop_generation(conv_id: str, *, discard: bool = False) -> None:
    run = _generations.get(conv_id)
    if not run:
        return
    run.cancelling = True
    if run.task and not run.task.done():
        run.task.cancel()
    if discard:
        _generations.pop(conv_id, None)


def spawn(coro) -> asyncio.Task:
    task = asyncio.get_running_loop().create_task(coro)
    _generation_tasks.add(task)
    task.add_done_callback(_generation_tasks.discard)
    return task


async def _pump_generation(run: GenerationRun, work) -> None:
    try:
        await work(run)
    except asyncio.CancelledError:
        pass
    except Exception:
        log.exception("listing generation pump failed")
    finally:
        run.finish()
        for conv_id, active in list(_generations.items()):
            if active is run:
                _forget_generation(conv_id, run)
                break


async def _follow_generation(run: GenerationRun):
    queue = run.subscribe()
    try:
        yield KEEPALIVE
        while True:
            item = await queue.get()
            if item is _DONE:
                break
            yield item
    finally:
        run.unsubscribe(queue)


async def wait_generation(conv_id: str) -> None:
    run = _generations.get(conv_id)
    if run and run.task:
        try:
            await run.task
        except asyncio.CancelledError:
            pass


async def reset_generations() -> None:
    for run in list(_generations.values()):
        if run.task and not run.task.done():
            run.cancelling = True
            run.task.cancel()
    _generations.clear()
    _generation_tasks.clear()


def stream_generation(run: GenerationRun) -> StreamingResponse:
    return StreamingResponse(_follow_generation(run), media_type="text/event-stream", headers=SSE_HEADERS)


def _sse_encode(text: str) -> str:
    return text.replace("\n", "\ndata: ")


def sse_data(text: str) -> str:
    return f"data: {_sse_encode(text)}\n\n"


def sse_event(event: str, text: str) -> str:
    return f"event: {event}\n{sse_data(text)}"


def sse_for_stream_item(item) -> tuple[str | None, str]:
    kind, text = unpack_stream_item(item)
    if not text:
        return None, ""
    if kind == "thinking":
        return sse_event("thinking", text), ""
    return sse_data(text), text


async def iter_with_keepalives(source, timeout: float = 3.0):
    iterator = source.__aiter__()
    pending = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(iterator.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=timeout)
            if not done:
                yield None
                continue
            try:
                item = pending.result()
            except StopAsyncIteration:
                return
            pending = None
            yield item
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            try:
                await pending
            except (asyncio.CancelledError, StopAsyncIteration, Exception):
                pass


async def wait_task_keepalives(task: asyncio.Task, timeout: float = 3.0):
    while not task.done():
        yield
        await asyncio.wait({task}, timeout=timeout)


async def await_with_pulses(run: GenerationRun, coro, child_tasks: list[asyncio.Task]):
    """Await a long step while pulsing SSE so mobile clients do not drop."""
    task = asyncio.create_task(coro)
    child_tasks.append(task)
    async for _ in wait_task_keepalives(task):
        run.pulse()
    return task.result()


def start_generation(conv_id: str, work: Callable[[GenerationRun], Awaitable[None]]) -> GenerationRun:
    """Register a run for this conversation and start pumping its work in the background."""
    run = GenerationRun()
    _generations[conv_id] = run
    run.task = spawn(_pump_generation(run, work))
    return run
