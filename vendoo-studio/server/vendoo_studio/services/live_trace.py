"""Let deep generation steps report what they are doing to the chat stream.

Photo analysis and sold-comps research sit several calls below the generate
run and return one finished result, so the chat saw nothing until their cards
landed. A generate run binds a sink here; the steps underneath call ``emit``
and the run relays it as SSE. With nothing bound, ``emit`` does nothing.

The sink lives in a context variable, so tasks the run spawns inherit it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextvars import ContextVar

log = logging.getLogger("vendoo_studio.chat")

Sink = Callable[[str, str], None]

_sink: ContextVar[Sink | None] = ContextVar("live_trace_sink", default=None)


def bind(sink: Sink | None) -> None:
    """Route this task's (and its children's) trace into ``sink``."""
    _sink.set(sink)


def emit(kind: str, text: str) -> None:
    """Report ``text`` as a ``thinking`` delta or a finished ``step`` line."""
    sink = _sink.get()
    if sink is None or not text:
        return
    try:
        sink(kind, text)
    except Exception:
        log.debug("live trace sink failed", exc_info=True)
