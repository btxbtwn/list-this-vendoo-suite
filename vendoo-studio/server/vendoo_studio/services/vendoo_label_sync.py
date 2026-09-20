"""Refresh draft / active / sold for every Studio listing bound to Vendoo.

Per-listing sync only runs when that listing is open. Sellers often relist in
Vendoo while looking at the sidebar, so labels drift. This pass pages the same
Firestore inventory Vendoo's own app reads, and for each item Studio already
knows it adopts Vendoo's inventory label — no photo downloads, no new imports,
no overwriting Studio form fields.

Runs when Studio regains focus or Chrome reconnects, debounced so a flurry of
focus events is one pass. Never on a fixed timer.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass
from types import SimpleNamespace

from vendoo_studio.models.conversation import utcnow

log = logging.getLogger("vendoo_studio.vendoo_label_sync")

# Same page size as bulk import: full documents stay a reasonable WS message.
PAGE_SIZE = 50
# Focus / reconnect can fire in bursts; one pass covers them.
MIN_INTERVAL_SEC = 45


@dataclass
class LabelSyncProgress:
    running: bool = False
    checked: int = 0
    updated: int = 0
    skipped: bool = False
    reason: str = ""
    started_at: str = ""
    finished_at: str = ""
    error: str = ""


_progress = LabelSyncProgress()
_task: asyncio.Task | None = None
_last_finished_mono: float = 0.0


def status() -> dict:
    return asdict(_progress)


def start(*, force: bool = False) -> dict:
    """Kick off a label pass, or report why this call did nothing."""
    global _task, _progress

    from vendoo_studio.services import vendoo_bulk_import

    if _task is not None and not _task.done():
        return {**status(), "skipped": True, "reason": "already running"}
    if vendoo_bulk_import.status().get("running"):
        _progress = LabelSyncProgress(
            skipped=True,
            reason="bulk import running",
            finished_at=utcnow().isoformat(),
        )
        return status()
    if not force and _last_finished_mono and (time.monotonic() - _last_finished_mono) < MIN_INTERVAL_SEC:
        _progress = LabelSyncProgress(
            skipped=True,
            reason="recent",
            finished_at=utcnow().isoformat(),
        )
        return status()

    _progress = LabelSyncProgress(running=True, started_at=utcnow().isoformat())
    _task = asyncio.create_task(_run())
    return status()


async def _list_page(page_token: str) -> tuple[list[dict], str]:
    from vendoo_studio.services.vendoo_create import run_ops

    reply = await run_ops(SimpleNamespace(id=None), [{
        "op": "list_items",
        "page_size": PAGE_SIZE,
        "page_token": page_token,
        "ids_only": False,
    }])
    hit = next((r for r in reply.get("results", []) if r.get("op") == "list_items"), {})
    items = hit.get("items") if isinstance(hit.get("items"), list) else []
    return items, str(hit.get("next_page_token") or "")


async def _run() -> None:
    global _last_finished_mono

    from vendoo_studio.database import SessionLocal
    from vendoo_studio.repositories.queries import ConversationRepo
    from vendoo_studio.services.vendoo_create import LOOKUP_TIMEOUT_SEC, label_display_map
    from vendoo_studio.services.vendoo_import import parse_notes
    from vendoo_studio.services.vendoo_watch import cache_pulled_item, refresh_inventory_label

    try:
        # Warm the id→name cache once per pass so Item Details can rename opaque
        # chips even when a later Regenerate cannot reach list_labels in time.
        try:
            await label_display_map(None, timeout=LOOKUP_TIMEOUT_SEC)
        except Exception:  # noqa: BLE001 - inventory pass still useful without names
            log.warning("Vendoo label catalog refresh skipped", exc_info=True)

        page_token = ""
        with SessionLocal() as db:
            conv_repo = ConversationRepo(db)
            while True:
                items, page_token = await _list_page(page_token)
                for item in items:
                    item_id = str(item.get("id") or item.get("itemID") or "").strip()
                    if not item_id:
                        continue
                    conv = conv_repo.find_by_vendoo_item_id(item_id)
                    if conv is None:
                        continue
                    _progress.checked += 1
                    before_label = str(parse_notes(conv.notes).get("vendooStatus") or "")
                    before_row = conv.status
                    label = refresh_inventory_label(db, conv.id, item)
                    cache_pulled_item(db, conv.id, item, source="vendoo_label_sync")
                    db.expire_all()
                    fresh = conv_repo.get(conv.id)
                    if label != before_label or (fresh is not None and fresh.status != before_row):
                        _progress.updated += 1
                if not page_token:
                    break
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced in status for the client
        log.exception("Vendoo label sync failed")
        _progress.error = str(exc)
    finally:
        _progress.running = False
        _progress.finished_at = utcnow().isoformat()
        _last_finished_mono = time.monotonic()
