"""In-memory ring of Vendoo HTTP calls reported by the extension.

Query strings, authorization headers, request bodies, and tokens never enter
the ring. The list lives only in this process: restarting Studio clears it.
"""

from __future__ import annotations

import re
import threading
from collections import deque
from datetime import UTC, datetime
from typing import Any

MAX_ENTRIES = 200
_SAFE_ERROR = re.compile(r"^(timed out|failed|HTTP [1-5]\d\d)$")
_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"})
_HOST = re.compile(r"^[A-Za-z0-9.-]{1,120}$")

_lock = threading.Lock()
_entries: deque[dict[str, Any]] = deque(maxlen=MAX_ENTRIES)
_seq = 0


def _at(value: object) -> str:
    text = str(value or "").strip()
    if len(text) > 40:
        text = ""
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = datetime.now(UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _status(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        code = int(value)
    except (TypeError, ValueError):
        return None
    if 100 <= code <= 599:
        return code
    return None


def _error(value: object, status: int | None, ok: bool) -> str | None:
    if ok:
        return None
    text = str(value or "").strip()
    if _SAFE_ERROR.fullmatch(text):
        return text
    if status is None:
        return "failed"
    return f"HTTP {status}"


def sanitize_entry(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    host = str(raw.get("host") or "").strip().lower()
    if not _HOST.fullmatch(host) or "@" in host:
        return None
    path = str(raw.get("path") or "/")
    path = path.split("?", 1)[0].split("#", 1)[0].strip() or "/"
    if not path.startswith("/") or "\\" in path or " " in path:
        return None
    path = path[:300]
    method = str(raw.get("method") or "GET").strip().upper()
    if method not in _METHODS:
        method = "GET"
    status = _status(raw.get("status"))
    ok = bool(raw.get("ok")) and status is not None and status < 400
    try:
        duration = int(raw.get("duration_ms") or 0)
    except (TypeError, ValueError):
        duration = 0
    duration = min(max(duration, 0), 600_000)
    return {
        "at": _at(raw.get("at")),
        "method": method,
        "host": host,
        "path": path,
        "status": status,
        "duration_ms": duration,
        "ok": ok,
        "error": _error(raw.get("error"), status, ok),
    }


def record(raw_entries: object) -> int:
    """Keep sanitized lines. Returns how many were stored."""
    global _seq
    if isinstance(raw_entries, dict):
        items = [raw_entries]
    elif isinstance(raw_entries, list):
        items = raw_entries[-MAX_ENTRIES:]
    else:
        return 0
    stored = 0
    with _lock:
        for raw in items:
            clean = sanitize_entry(raw)
            if clean is None:
                continue
            _seq += 1
            clean["id"] = _seq
            _entries.append(clean)
            stored += 1
    return stored


def ingest(payload: object) -> int:
    if isinstance(payload, dict) and isinstance(payload.get("entries"), list):
        return record(payload["entries"])
    return record(payload)


def list_entries() -> list[dict[str, Any]]:
    with _lock:
        return list(reversed(_entries))


def clear() -> None:
    with _lock:
        _entries.clear()
