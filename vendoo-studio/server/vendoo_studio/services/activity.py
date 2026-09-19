"""Work Studio is still doing for a listing after (or beside) the chat stream.

Chat used to treat the end of its SSE stream as "done", but generation keeps
filling discovered fields afterwards, chat saves run as their own task, and
Vendoo syncs post to the conversation too. Everything that can still write to a
listing registers here so chat can show it and Stop can cancel it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(eq=False)
class Work:
    conv_id: str
    label: str
    task: asyncio.Task | None = None
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True
        if self.task is not None and not self.task.done():
            self.task.cancel()


_work: dict[str, list[Work]] = {}


def begin(conv_id: str, label: str) -> Work:
    """Register work the caller runs inline; call ``end`` when it stops."""
    work = Work(conv_id, label)
    _work.setdefault(conv_id, []).append(work)
    return work


def end(work: Work) -> None:
    items = _work.get(work.conv_id)
    if not items:
        return
    if work in items:
        items.remove(work)
    if not items:
        _work.pop(work.conv_id, None)


def track_task(conv_id: str, label: str, task: asyncio.Task) -> asyncio.Task:
    """Register a background task until it finishes; Stop cancels it."""
    work = begin(conv_id, label)
    work.task = task
    task.add_done_callback(lambda _task: end(work))
    return task


def running(conv_id: str) -> list[str]:
    labels = [work.label for work in _work.get(conv_id, []) if not work.cancelled]
    return list(dict.fromkeys(labels))


def cancel(conv_id: str) -> int:
    items = list(_work.get(conv_id, []))
    for work in items:
        work.cancel()
    return len(items)


def reset() -> None:
    for items in list(_work.values()):
        for work in items:
            work.cancel()
    _work.clear()
