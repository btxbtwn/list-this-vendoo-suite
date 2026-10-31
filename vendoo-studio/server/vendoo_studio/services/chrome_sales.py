"""Notice sales on marketplaces that sign in through Chrome.

eBay and Etsy push a sale through the relay. For the others the extension
reads the seller's sold list, or the live closet, in a few requests however
many listings are still up. Shops take turns, and the gap before the next
check is between four and twelve minutes. Anteroom sends every listing it still has live
there. A sold item counts only when Anteroom still has it live on that
marketplace, so a sale Anteroom already knows, or one it never listed, is not
reported. The extension returns listing IDs only. Delisting the other
marketplaces happens only when the seller turned that option on.

Facebook has no seller list Anteroom can read yet, so each listing's own page
is read: a few listings per check, taking turns, with a longer gap between
checks than the other shops.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

from sqlalchemy.orm import Session

from vendoo_studio.services.relay_sales import record_sale
from vendoo_studio.services.user_settings import sale_detection_enabled

log = logging.getLogger("vendoo_studio.chrome_sales")

CHROME_MARKETS = ("poshmark", "mercari", "depop", "sellwild", "vinted", "facebook")
# Facebook's check opens each listing's own page in Chrome, and the item already
# has its own Check on Facebook, so opening an item must not start that by
# itself. The timed pass still covers it.
ITEM_CHECK_MARKETS = tuple(name for name in CHROME_MARKETS if name != "facebook")
POLL_INTERVAL_S = 30
MIN_GAP_S = 4 * 60
MAX_GAP_S = 12 * 60
GAPS = {"facebook": (20 * 60, 40 * 60)}
# Listings read per check, for marketplaces read one listing at a time.
BATCH = {"facebook": 6}
MAX_CHECKED = 5000
MAX_REPORTED = 40

# Matches the IDs marketplace_delist reads from each listing link.
_LISTING_ID = {
    "poshmark": re.compile(r"^[a-f0-9]{24}$"),
    "mercari": re.compile(r"^m\d{6,}$"),
    "depop": re.compile(r"^[a-z0-9][a-z0-9-]{0,200}$"),
    "sellwild": re.compile(r"^\d{1,15}$"),
    "vinted": re.compile(r"^\d{1,15}$"),
    "facebook": re.compile(r"^\d{6,20}$"),
}
_HOST = {"poshmark": "poshmark.com", "mercari": "mercari.com", "depop": "depop.com", "sellwild": "sellwild.com",
         "vinted": "vinted.com", "facebook": "facebook.com"}

# An item opened in Anteroom reads its own listings at most this often per
# shop. Browsing items must not read a marketplace more than the timed checks do.
ITEM_GAP_S = 60

_task: asyncio.Task | None = None
_next: dict[str, float] = {}
_errors: dict[str, str] = {}
_turn: dict[str, int] = {}
_item_read: dict[str, float] = {}


def check_errors() -> dict[str, str]:
    return dict(_errors)


def clear_check_error(marketplace: str) -> None:
    _errors.pop(marketplace, None)


def arm_next(marketplace: str, now: float) -> float:
    """The next check for this shop, somewhere between four and twelve minutes out (Facebook: 20 to 40)."""
    low, high = GAPS.get(marketplace, (MIN_GAP_S, MAX_GAP_S))
    due = now + random.uniform(low, high)
    _next[marketplace] = due
    return due


def normalize_sales(marketplace: str, raw: object) -> list[str]:
    """Keep listing IDs that match this marketplace. Drop everything else."""
    if marketplace not in _LISTING_ID or not isinstance(raw, dict) or raw.get("ok") is not True:
        return []
    sales = raw.get("sales")
    if not isinstance(sales, list):
        return []
    pattern = _LISTING_ID[marketplace]
    found: list[str] = []
    for item in sales[:MAX_REPORTED]:
        listing = item.get("listing_id") if isinstance(item, dict) else None
        if isinstance(listing, str) and pattern.fullmatch(listing) and listing not in found:
            found.append(listing)
    return found


def next_batch(marketplace: str, listing_ids: list[str]) -> list[str]:
    """This check's share of the listings, for marketplaces read one listing at a time. The next check starts after it."""
    size = BATCH.get(marketplace)
    if not size or len(listing_ids) <= size:
        return listing_ids[:MAX_CHECKED]
    start = _turn.get(marketplace, 0) % len(listing_ids)
    _turn[marketplace] = start + size
    return (listing_ids[start:] + listing_ids[:start])[:size]


def _recorded_sales(db: Session, conv_ids, marketplace: str | None = None) -> dict[tuple[str, str], set[str | None]]:
    """The listing IDs Anteroom itself recorded a sale for, by conversation and marketplace."""
    from vendoo_studio.models.marketplace_sale import PAID_STATUSES, MarketplaceSale

    recorded: dict[tuple[str, str], set[str | None]] = {}
    if not conv_ids:
        return recorded
    query = db.query(MarketplaceSale.conversation_id, MarketplaceSale.marketplace, MarketplaceSale.listing_id).filter(
        MarketplaceSale.conversation_id.in_(list(conv_ids)), MarketplaceSale.order_status.in_(PAID_STATUSES))
    if marketplace:
        query = query.filter(MarketplaceSale.marketplace == marketplace)
    for conv_id, name, listing_id in query.all():
        recorded.setdefault((cast(str, conv_id), name), set()).add(listing_id)
    return recorded


def _needs_sale_check(entry: dict, listing_id: str, recorded: set[str | None]) -> bool:
    """False for a listing whose sale Anteroom recorded. A sale only the imported notes claim is still checked."""
    return entry.get("state") == "live" and listing_id not in recorded and None not in recorded


def live_listing_ids(marketplace: str, *, session_factory=None) -> dict[str, str]:
    """Listing IDs to read for a sale, each mapped to the item that has it live.

    Live means not delisted or marked not listed, and without a sale of its own
    on the ledger: a sale only the imported notes claim is read, so the
    marketplace confirms it. The item travels with the ID so a sale found on
    the listing protects the item it belongs to, even when its link is odd.
    """
    from vendoo_studio.models.conversation import Conversation
    from vendoo_studio.models.marketplace_listing import MarketplaceListing
    from vendoo_studio.services.marketplace_delist import listings

    if session_factory is None:
        from vendoo_studio.database import SessionLocal

        session_factory = SessionLocal
    found: dict[str, str] = {}
    with session_factory() as db:
        # Vendoo's links and the seller's marks live in the notes; direct listings have their own table.
        noted = db.query(Conversation.id).filter(Conversation.notes.contains(_HOST[marketplace]))
        direct = db.query(MarketplaceListing.conversation_id).filter(
            MarketplaceListing.marketplace == marketplace, MarketplaceListing.listing_url.isnot(None))
        conv_ids = dict.fromkeys(row[0] for row in [*direct.all(), *noted.all()])
        recorded = _recorded_sales(db, conv_ids, marketplace)
        for conv_id in conv_ids:
            entry = listings(db, conv_id).get(marketplace) or {}
            listing_id = entry.get("listing_id")
            if listing_id and _needs_sale_check(entry, listing_id, recorded.get((conv_id, marketplace), set())) \
                    and listing_id not in found:
                found[listing_id] = conv_id
    return found


def _already_sold(db: Session, conv_id: str) -> bool:
    """True when every unit is sold and a sale is already on the ledger.

    Then a listing Anteroom reads as sold is the seller clearing the other
    listings, not another order, whatever marketplace it is on. An item still
    on sale (a relist, or stock left) keeps detecting sales. An item that only
    a label calls sold has no ledger sale yet, so its first report is recorded.
    """
    from vendoo_studio.models.conversation import Conversation
    from vendoo_studio.models.marketplace_sale import PAID_STATUSES, MarketplaceSale
    from vendoo_studio.services.item_status import status_for
    from vendoo_studio.services.vendoo_import import parse_notes

    if not db.query(MarketplaceSale.id).filter(
            MarketplaceSale.conversation_id == conv_id, MarketplaceSale.order_status.in_(PAID_STATUSES)).first():
        return False
    conv = db.get(Conversation, conv_id)
    return bool(conv and status_for(db, conv_id, parse_notes(conv.notes)).status == "sold")


def _claimed_sold_at(db: Session, conv_id: str, marketplace: str) -> datetime | None:
    """When the imported notes say this marketplace sold the item, if they do.

    A check confirms a claim Anteroom already has; the sale keeps the date it
    was made instead of landing in the month the check ran.
    """
    from vendoo_studio.models.conversation import Conversation
    from vendoo_studio.services.vendoo_import import parse_notes

    conv = db.get(Conversation, conv_id)
    notes = parse_notes(conv.notes) if conv else {}
    sale = notes.get("vendooSale") if isinstance(notes.get("vendooSale"), dict) else {}
    dates = notes.get("vendooDates") if isinstance(notes.get("vendooDates"), dict) else {}
    sold_by = dates.get("soldByMarketplace") if isinstance(dates.get("soldByMarketplace"), dict) else {}
    claimed = sold_by.get(marketplace)
    if not claimed and str(sale.get("marketplace") or "") == marketplace:
        claimed = sale.get("soldAt")
    if not claimed:
        return None
    try:
        parsed = datetime.fromisoformat(str(claimed).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed


def record_reported_sales(marketplace: str, listing_ids: list[str], *, session_factory=None,
                          conversation_ids: dict[str, str] | None = None) -> list[str]:
    """Store each sold listing once, against the item that was read. Returns the new sale IDs.

    A sale that arrived before its item could be matched is attached now: the
    item came from the check itself, so the listing it found sold is protected
    from then on, whatever its link looks like.

    A listing reading sold is not a sale when the item already sold on another
    marketplace: that is the seller clearing the other listings, not a second
    order.
    """
    from vendoo_studio.models.marketplace_sale import MarketplaceSale

    if session_factory is None:
        from vendoo_studio.database import SessionLocal

        session_factory = SessionLocal
    created: list[str] = []
    with session_factory() as db:
        for listing_id in listing_ids:
            conv_id = (conversation_ids or {}).get(listing_id)
            if conv_id and _already_sold(db, conv_id):
                continue
            sale = record_sale(
                db,
                marketplace=marketplace,
                order_id=listing_id,
                line_id=listing_id,
                listing_id=listing_id,
                quantity=None,
                sold_at=_claimed_sold_at(db, conv_id, marketplace) if conv_id else None,
                conversation_id=conv_id,
            )
            if sale:
                created.append(sale.id)
            elif conv_id:
                db.query(MarketplaceSale).filter(
                    MarketplaceSale.marketplace == marketplace, MarketplaceSale.listing_id == listing_id,
                    MarketplaceSale.conversation_id.is_(None),
                ).update({"conversation_id": conv_id}, synchronize_session=False)
                db.commit()
    return created


async def check_marketplace(marketplace: str) -> bool:
    """Read this shop's sales. False when Chrome could not check it."""
    from vendoo_studio.services import browser_bridge
    from vendoo_studio.services.marketplace_accounts import announce_sales

    if marketplace not in CHROME_MARKETS or not sale_detection_enabled(marketplace):
        clear_check_error(marketplace)
        return True
    live = await asyncio.to_thread(live_listing_ids, marketplace)
    listing_ids = next_batch(marketplace, list(live))
    if not listing_ids:
        clear_check_error(marketplace)
        return True
    try:
        raw = await browser_bridge.request(
            SimpleNamespace(id=None),
            "marketplace.sales",
            {"marketplace": marketplace, "listing_ids": listing_ids},
            timeout=90,
        )
    except browser_bridge.BrowserBridgeError:
        return False
    if not isinstance(raw, dict) or raw.get("skipped") is True:
        return False
    if raw.get("ok") is not True:
        _errors[marketplace] = "Couldn't check sales. Sign in again in Chrome if this keeps happening."
        return False
    clear_check_error(marketplace)
    sold = [listing_id for listing_id in normalize_sales(marketplace, raw) if listing_id in live]
    if sold:
        created = await asyncio.to_thread(record_reported_sales, marketplace, sold, conversation_ids=live)
        if created:
            await announce_sales(created)
    return True


async def check_now(marketplace: str) -> bool:
    """Check one shop when the seller asks. Its next timed check moves a full gap out."""
    arm_next(marketplace, time.time())
    return await check_marketplace(marketplace)


def live_item_listings(db: Session, conv_id: str) -> dict[str, str]:
    """Listing IDs this item has on marketplaces Chrome reads, and whose sale Anteroom has not seen itself.

    A marketplace Anteroom recorded a sale for is settled. One that reads sold
    only from the imported notes is still checked, so that claim is confirmed
    on the marketplace instead of being believed.
    """
    from vendoo_studio.services.marketplace_delist import listings

    recorded = _recorded_sales(db, [conv_id])
    found: dict[str, str] = {}
    for marketplace, entry in listings(db, conv_id).items():
        listing_id = entry.get("listing_id")
        if marketplace not in ITEM_CHECK_MARKETS or not listing_id:
            continue
        if _needs_sale_check(entry, listing_id, recorded.get((conv_id, marketplace), set())):
            found[marketplace] = listing_id
    return found


async def check_item(db: Session, conv_id: str, *, session_factory=None) -> dict:
    """Read this item's live listings now, so a sale shows while the seller looks at it.

    Opening an item brings each of its shops' next check forward to this item
    alone, which is what makes a sale read as live instead of waiting for the
    shop's own turn. A shop is read at most once a minute however many items
    the seller opens, and its timed checks keep their own schedule. A sale the
    imported notes claim is checked the same way, so Anteroom believes only
    what a marketplace tells it. Only the listing IDs travel, and nothing on
    any marketplace changes.
    """
    from vendoo_studio.services.extension_connection import extension_manager
    from vendoo_studio.services import browser_bridge

    result: dict = {"ok": True, "checked": [], "recorded": [], "skipped": None}
    wanted = {name: listing_id for name, listing_id in live_item_listings(db, conv_id).items()
              if sale_detection_enabled(name)}
    if not wanted:
        result["skipped"] = "No live listing to check."
        return result
    if not extension_manager.connected:
        result.update(ok=False, skipped="Connect Chrome first.")
        return result
    now = time.time()
    due = {name: listing_id for name, listing_id in wanted.items()
           if now - _item_read.get(name, 0) >= ITEM_GAP_S}
    if not due:
        result["skipped"] = "Just checked."
        return result
    sold: dict[str, str] = {}
    for marketplace, listing_id in due.items():
        try:
            raw = await browser_bridge.request(
                SimpleNamespace(id=None),
                "marketplace.sales",
                {"marketplace": marketplace, "listing_ids": [listing_id]},
                timeout=90,
            )
        except browser_bridge.BrowserBridgeError:
            continue
        if not isinstance(raw, dict) or raw.get("skipped") is True or raw.get("ok") is not True:
            continue
        _item_read[marketplace] = time.time()
        result["checked"].append(marketplace)
        if listing_id in normalize_sales(marketplace, raw):
            sold[marketplace] = listing_id
    if not sold:
        return result
    from vendoo_studio.services.marketplace_accounts import announce_sales

    for marketplace, listing_id in sold.items():
        created = await asyncio.to_thread(record_reported_sales, marketplace, [listing_id], session_factory=session_factory,
                                          conversation_ids={listing_id: conv_id})
        result["recorded"].extend(created)
    if result["recorded"]:
        await announce_sales(result["recorded"], session_factory=session_factory)
    return result


async def check_due() -> None:
    """Check one shop. The others wait for their own turn, on uneven gaps."""
    now = time.time()
    for marketplace in CHROME_MARKETS:
        if not sale_detection_enabled(marketplace):
            clear_check_error(marketplace)
            _next.pop(marketplace, None)
            continue
        if _next.get(marketplace, 0) > now:
            continue
        arm_next(marketplace, now)
        try:
            await check_marketplace(marketplace)
        except Exception:  # noqa: BLE001 - one marketplace must not stop the others
            log.debug("could not check %s sales", marketplace, exc_info=True)
            _errors[marketplace] = "Couldn't check sales. Sign in again in Chrome if this keeps happening."
        return


async def _watch() -> None:
    while True:
        await asyncio.sleep(POLL_INTERVAL_S)
        try:
            await check_due()
        except Exception:  # noqa: BLE001 - one bad pass must not stop the watcher
            log.exception("Sale check failed")


def start_chrome_sales() -> asyncio.Task:
    """Check Chrome marketplaces on an interval. Call from the running event loop."""
    global _task
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(_watch())
    return _task


def stop_chrome_sales() -> None:
    if _task is not None and not _task.done():
        _task.cancel()
