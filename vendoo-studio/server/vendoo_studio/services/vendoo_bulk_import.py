"""Pull the seller's whole Vendoo inventory into Studio in one run.

Vendoo keeps every item as a Firestore document under ``users/{uid}/items``,
which its own inventory page reads, so one paged listing enumerates the account
without an ``/api/item`` call per listing. Each item is imported whole, photos
included, so a finished run leaves nothing to fetch later.

Re-running is a sync in both directions: an item whose Vendoo document has not
changed since the last pass is skipped, so nothing local is overwritten without
a reason, and a bound listing the inventory no longer carries is deleted here,
so what Studio shows is what Vendoo has.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from types import SimpleNamespace

from vendoo_studio.models.conversation import utcnow

log = logging.getLogger("vendoo_studio.vendoo_bulk_import")

# Full item documents, so a page stays a reasonable WebSocket message.
PAGE_SIZE = 50
# The counting pass masks documents down to their id.
COUNT_PAGE_SIZE = 300


@dataclass
class BulkImportProgress:
    running: bool = False
    total: int = 0
    processed: int = 0
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    deleted: int = 0
    photos: int = 0
    current_title: str = ""
    started_at: str = ""
    finished_at: str = ""
    cancelled: bool = False
    error: str = ""
    failures: list[dict] = field(default_factory=list)


_progress = BulkImportProgress()
_task: asyncio.Task | None = None


def status() -> dict:
    return asdict(_progress)


def start() -> dict:
    """Kick off a run beside the request that asked for it."""
    global _task, _progress

    if _task is not None and not _task.done():
        raise RuntimeError("A Vendoo import is already running.")
    _progress = BulkImportProgress(running=True, started_at=utcnow().isoformat())
    _task = asyncio.create_task(_run())
    return status()


def cancel() -> bool:
    if _task is None or _task.done():
        return False
    _progress.cancelled = True
    _task.cancel()
    return True


async def _list_page(page_token: str, *, ids_only: bool = False) -> tuple[list[dict], str]:
    from vendoo_studio.services.vendoo_create import run_ops

    reply = await run_ops(SimpleNamespace(id=None), [{
        "op": "list_items",
        "page_size": COUNT_PAGE_SIZE if ids_only else PAGE_SIZE,
        "page_token": page_token,
        "ids_only": ids_only,
    }])
    hit = next((r for r in reply.get("results", []) if r.get("op") == "list_items"), {})
    items = hit.get("items") if isinstance(hit.get("items"), list) else []
    return items, str(hit.get("next_page_token") or "")


async def _count_items() -> int:
    total = 0
    page_token = ""
    while True:
        items, page_token = await _list_page(page_token, ids_only=True)
        total += len(items)
        if not page_token:
            return total


async def _run() -> None:
    from vendoo_studio.database import SessionLocal
    from vendoo_studio.repositories.queries import ConversationRepo
    from vendoo_studio.services.vendoo_import import (
        attach_vendoo_photos,
        image_urls_from_vendoo,
        import_vendoo_item,
        merge_notes,
        parse_notes,
        vendoo_dates,
        vendoo_item_status,
        vendoo_listed_marketplaces,
        vendoo_sale,
        vendoo_updated_at,
    )

    def photos_missing(conv_id: str, item: dict) -> bool:
        """True when the item has photos and none of them are here."""
        return bool(image_urls_from_vendoo(item, None)) and not conv_repo.get_photos(conv_id)

    def refresh_status(conv, item: dict) -> bool:
        """Re-read Vendoo's label for an unchanged item, and say if it moved.

        A pass that skips an item still costs nothing to relabel, so a listing
        Studio read as a draft before it learned to see a sale record is put
        right on the next run instead of waiting for Vendoo to touch it.
        """
        notes = parse_notes(conv.notes)
        status = vendoo_item_status(item, None)
        marketplaces = vendoo_listed_marketplaces(item, None)
        dates = vendoo_dates(item, None)
        sale = vendoo_sale(item, None)
        if (
            notes.get("vendooStatus") == status
            and notes.get("vendooMarketplaces") == marketplaces
            and notes.get("vendooDates") == dates
            and (notes.get("vendooSale") or {}) == sale
        ):
            return False
        conv.notes = merge_notes(conv.notes, {
            "vendooStatus": status,
            "vendooMarketplaces": marketplaces,
            "vendooDates": dates,
            "vendooSale": sale,
        })
        conv_repo.update_status(conv.id, status)
        db.commit()
        return True

    try:
        _progress.total = await _count_items()
        page_token = ""
        seen_ids: set[str] = set()
        with SessionLocal() as db:
            conv_repo = ConversationRepo(db)
            while True:
                items, page_token = await _list_page(page_token)
                for item in items:
                    item_id = str(item.get("id") or "").strip()
                    if not item_id:
                        continue
                    seen_ids.add(item_id)
                    title = _item_title(item)
                    _progress.current_title = title
                    try:
                        existing = conv_repo.find_by_vendoo_item_id(item_id)
                        seen_at = parse_notes(existing.notes).get("vendooUpdatedAt") if existing else None
                        if existing is not None and seen_at and seen_at == vendoo_updated_at(item):
                            # Vendoo has not touched the item, so the fields are
                            # current; only its label and missing photos are
                            # worth a look.
                            relabelled = refresh_status(existing, item)
                            if not photos_missing(existing.id, item):
                                if relabelled:
                                    _progress.updated += 1
                                else:
                                    _progress.skipped += 1
                                continue
                            added = await attach_vendoo_photos(db, existing.id, item)
                            _progress.photos += added
                            _progress.updated += 1
                            continue
                        result = await import_vendoo_item(
                            db,
                            item_id=item_id,
                            item=item,
                            source="bulk",
                        )
                        _progress.photos += int(result["photo_count"])
                        if result["reused"]:
                            _progress.updated += 1
                        else:
                            _progress.imported += 1
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001 - one bad item must not end the run
                        log.warning("Vendoo bulk import failed for %s: %s", item_id, exc)
                        db.rollback()
                        _progress.failed += 1
                        if len(_progress.failures) < 20:
                            _progress.failures.append({
                                "item_id": item_id,
                                "title": title,
                                "error": str(exc),
                            })
                    finally:
                        _progress.processed += 1
                if not page_token:
                    break
            _delete_missing(db, conv_repo, seen_ids)
    except asyncio.CancelledError:
        _progress.cancelled = True
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced in the import panel
        log.exception("Vendoo bulk import failed")
        _progress.error = str(exc)
    finally:
        _progress.running = False
        _progress.current_title = ""
        _progress.finished_at = utcnow().isoformat()


def _delete_missing(db, conv_repo, seen_ids: set[str]) -> None:
    """Drop the listings whose Vendoo item was not in the inventory.

    Only a run that reached the last page gets here, so an item is missing
    because the seller deleted it in Vendoo, not because the pass stopped
    early. Listings that were never bound to a Vendoo item are left alone.
    """
    from vendoo_studio.services.listing_delete import ListingBusy, delete_listing

    if not seen_ids:
        # An inventory that reads as empty is far likelier a Vendoo session
        # that went quiet than an account with nothing in it, and a sweep on
        # that reading would take the whole sidebar with it.
        log.warning("Vendoo inventory came back empty; leaving local listings alone")
        return

    for conv_id, item_id in conv_repo.vendoo_bound_item_ids().items():
        if item_id in seen_ids:
            continue
        try:
            delete_listing(db, conv_id)
        except ListingBusy:
            log.info("Vendoo item %s is gone but its listing is busy; keeping it", item_id)
            continue
        except Exception as exc:  # noqa: BLE001 - one stuck listing must not end the sweep
            log.warning("Could not delete the listing for deleted Vendoo item %s: %s", item_id, exc)
            db.rollback()
            continue
        _progress.deleted += 1


def _item_title(item: dict) -> str:
    general = item.get("generalDetails") if isinstance(item.get("generalDetails"), dict) else {}
    return str(general.get("title") or "").strip()
