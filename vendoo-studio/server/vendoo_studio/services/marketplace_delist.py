"""Seller-confirmed delisting: delete an item's live listings on named marketplaces.

Delist means the listing is removed from the marketplace. eBay has no delete,
so its listing is ended; Sellwild gives sellers only its own delist. Facebook
listings are linked and watched for sales, but the seller deletes them on
Facebook: its delete request has not been recorded from a signed-in client. The
marketplace where the item sold is never touched. Nothing here runs on a
timer, a queue, or a retry: each call names its marketplaces and carries the
seller's confirmation. Deleting is safe to repeat, because every marketplace
step reads the listing first and reports one that is already gone as deleted.

The seller can also correct what Anteroom knows: mark a marketplace listed
(with its link), sold, or not listed. A mark changes only Anteroom's record,
never the marketplace, and stands until the marketplace reports something
newer: a sale after a "listed" mark, or a different listing after a "not
listed" one.
"""
from __future__ import annotations

from datetime import UTC, datetime

import httpx
from sqlalchemy.orm import Session

from vendoo_studio.models.marketplace_listing import UNSETTLED_STATES
from vendoo_studio.models.marketplace_sale import MarketplaceSale, PAID_STATUSES
from vendoo_studio.repositories.marketplace_listings import MarketplaceListingRepo
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services import browser_bridge, marketplace_accounts
from vendoo_studio.services.api_job_lock import api_job_is_live, claim_api_job, release_api_job, start_gate
from vendoo_studio.services.listing_result import scrub
from vendoo_studio.services.marketplace_identity import listing_id, listing_reference
from vendoo_studio.services.vendoo_import import merge_notes, parse_notes

MARKETPLACES = ("ebay", "etsy", "poshmark", "mercari", "depop", "sellwild", "vinted", "facebook")
BROWSER_MARKETPLACES = {"poshmark", "mercari", "depop", "sellwild", "vinted"}
# Linked and watched, but Anteroom cannot delete them: the seller does that on the marketplace.
MANUAL_DELIST = frozenset({"facebook"})

class DelistError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _time(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _sold_on(db: Session, conv_id: str, notes: dict) -> dict[str, datetime | None]:
    """Where the item sold, and when that was last reported (None when unknown)."""
    sold: dict[str, datetime | None] = {}

    def add(marketplace: str, when) -> None:
        stamp, known = _time(when), sold.get(marketplace)
        sold[marketplace] = max(filter(None, (stamp, known)), default=None)

    from vendoo_studio.services.sale_inventory import stock_after_sale

    native = MarketplaceListingRepo(db).for_conversation(conv_id)
    stocks = {}
    for row in db.query(MarketplaceSale).filter(MarketplaceSale.conversation_id == conv_id, MarketplaceSale.order_status.in_(PAID_STATUSES)):
        mark = _notes_dict(notes, "marketplaceMarks").get(row.marketplace) or {}
        url, _source = current_listing(row.marketplace, (native.get(row.marketplace) or {}).get("listing_url"),
                                       _notes_dict(notes, "vendooListingUrls").get(row.marketplace), mark)
        current_id = listing_id(row.marketplace, url)
        if current_id and row.listing_id and current_id != row.listing_id:
            continue
        key = (row.marketplace, row.listing_id)
        if key not in stocks:
            stocks[key] = stock_after_sale(db, conv_id, row.marketplace, row.listing_id)
        if stocks[key]["status"] == "sold_out":
            add(row.marketplace, row.received_at)
    sale = notes.get("vendooSale") if isinstance(notes.get("vendooSale"), dict) else {}
    if sale.get("marketplace"):
        add(str(sale["marketplace"]).lower(), None)
    dates = notes.get("vendooDates") if isinstance(notes.get("vendooDates"), dict) else {}
    sold_by = dates.get("soldByMarketplace") if isinstance(dates.get("soldByMarketplace"), dict) else {}
    for name, when in sold_by.items():
        if when:
            add(str(name).lower(), when)
    return sold


def _notes_dict(notes: dict, key: str) -> dict:
    value = notes.get(key)
    return value if isinstance(value, dict) else {}


def current_listing(marketplace: str, anteroom_url, vendoo_url, mark: dict) -> tuple[str | None, str | None]:
    """The listing link that names this marketplace's listing now, and who reported it."""
    candidates = [(anteroom_url, "anteroom"), (vendoo_url, "vendoo")]
    if mark.get("state") == "listed":
        candidates.insert(0, (mark.get("url"), "seller"))
    return next(((url, source) for url, source in candidates if listing_id(marketplace, url)), (None, None))


def removed_marketplaces(notes: dict, anteroom_urls: dict[str, str]) -> list[str]:
    """Marketplaces where Anteroom deleted the listing, or the seller marked it not listed.

    Vendoo is never told about a direct delist, so its record keeps calling the
    item listed there. A newer listing than the one removed counts as live again.
    """
    urls = _notes_dict(notes, "vendooListingUrls")
    delists = _notes_dict(notes, "marketplaceDelists")
    marks = _notes_dict(notes, "marketplaceMarks")
    removed = []
    for marketplace in MARKETPLACES:
        mark = marks.get(marketplace) if isinstance(marks.get(marketplace), dict) else {}
        record = delists.get(marketplace) if isinstance(delists.get(marketplace), dict) else {}
        # Inventory reads call this for every item. Only removal records need
        # URL resolution to check whether a newer listing superseded them.
        if mark.get("state") != "not_listed" and record.get("state") != "deleted":
            continue
        url, _source = current_listing(marketplace, anteroom_urls.get(marketplace), urls.get(marketplace), mark)
        item_id = listing_id(marketplace, url)
        if mark.get("state") == "not_listed" and (not item_id or item_id == mark.get("listing_id")):
            removed.append(marketplace)
        elif record.get("state") == "deleted" and (not item_id or item_id == record.get("listing_id")):
            removed.append(marketplace)
    return removed


def listings(db: Session, conv_id: str) -> dict:
    """Each marketplace listing Anteroom knows for this item, and what Delist would do."""
    conv = ConversationRepo(db).get(conv_id)
    if not conv:
        raise DelistError(404, "Conversation not found")
    notes = parse_notes(conv.notes)
    urls = _notes_dict(notes, "vendooListingUrls")
    native = MarketplaceListingRepo(db).for_conversation(conv_id)
    delists = _notes_dict(notes, "marketplaceDelists")
    marks = _notes_dict(notes, "marketplaceMarks")
    sold = _sold_on(db, conv_id, notes)
    result = {}
    for marketplace in MARKETPLACES:
        binding = native.get(marketplace) if isinstance(native.get(marketplace), dict) else {}
        mark = marks.get(marketplace) if isinstance(marks.get(marketplace), dict) else {}
        url, source = current_listing(marketplace, binding.get("listing_url"), urls.get(marketplace), mark)
        item_id = listing_id(marketplace, url)
        if mark.get("state") == "not_listed" and (not item_id or item_id == mark.get("listing_id")):
            continue
        sold_here = marketplace in sold
        if mark.get("state") == "listed":
            reported, marked = sold.get(marketplace), _time(mark.get("at"))
            sold_here = bool(reported and marked and reported > marked)
        elif mark.get("state") == "sold":
            sold_here = True
        record = delists.get(marketplace) if isinstance(delists.get(marketplace), dict) else {}
        if not url and not record and not sold_here:
            continue
        item_id = item_id or record.get("listing_id")
        # A newer listing than the one deleted is live again.
        if record and item_id and record.get("listing_id") != item_id:
            record = {}
        result[marketplace] = {"url": url or record.get("url"), "listing_id": item_id, "source": source,
                               "sold_here": sold_here, "state": record.get("state") or "live",
                               "can_delist": marketplace not in MANUAL_DELIST,
                               "error": record.get("error"), "marketplace_message": record.get("marketplace_message"),
                               "at": record.get("at")}
    return result


def _store(db: Session, conv_id: str, key: str, marketplace: str, value: dict | None) -> None:
    conv = ConversationRepo(db).get(conv_id)
    db.refresh(conv)
    current = _notes_dict(parse_notes(conv.notes), key)
    current = {name: entry for name, entry in current.items() if name != marketplace}
    conv.notes = merge_notes(conv.notes, {key: {**current, **({marketplace: value} if value else {})}})
    db.commit()


def _record(db: Session, conv_id: str, marketplace: str, value: dict) -> None:
    _store(db, conv_id, "marketplaceDelists", marketplace, value)


MARKS = ("listed", "sold", "not_listed")


def mark(db: Session, conv_id: str, marketplace: str, state: str, url: str | None = None) -> dict:
    # Serialise duplicate validation and the local write with other seller
    # marks and direct action starts in this process.
    with start_gate():
        return _mark(db, conv_id, marketplace, state, url)


def _mark(db: Session, conv_id: str, marketplace: str, state: str, url: str | None) -> dict:
    """Record what the seller says about one marketplace. The marketplace itself is not touched.

    A mark also settles an unconfirmed direct listing: the seller has looked.
    """
    if marketplace not in MARKETPLACES or state not in MARKS:
        raise DelistError(400, "Name a marketplace and what to mark it as.")
    if any(str(job.current_step or "") == "native_delist" and job.conversation_id == conv_id for job in JobRepo(db).get_running()):
        raise DelistError(409, "A delist is running. Wait for it to finish.")
    known = listings(db, conv_id).get(marketplace) or {}
    # Full precision: a sale reported later in the same second must still count as newer.
    value: dict = {"state": state, "at": datetime.now(UTC).isoformat()}
    if state == "listed":
        reference = listing_reference(marketplace, url)
        if not reference:
            raise DelistError(400, f"Paste the {marketplace.title()} listing link, as it appears in the browser's address bar.")
        item_id, clean = reference
        from vendoo_studio.services.relay_sales import matching_listings

        if any(conv.id != conv_id for conv in matching_listings(db, marketplace, item_id)):
            raise DelistError(409, "This marketplace listing is already linked to another item. Resolve the duplicate before linking it here.")
        value.update(url=clean, listing_id=item_id)
    else:
        value.update(url=known.get("url"), listing_id=known.get("listing_id"))
    records = MarketplaceListingRepo(db)
    record = records.get(conv_id, marketplace)
    if record.get("job_id") and api_job_is_live(record["job_id"]):
        raise DelistError(409, f"The {marketplace.title()} action is still running. Wait for it to finish.")
    cleared = {"error": None, "error_code": None, "error_fields": None, "marketplace_message": None, "retry_after": None,
               "etsy_pending_write": None}
    if state == "not_listed" and record.get("state") in {*UNSETTLED_STATES, "published", "pending_review"}:
        from vendoo_studio.services.native_marketplaces import _resting_state

        # Not live: keep the marketplace IDs so a new List reuses them, drop the link.
        records.save(conv_id, marketplace, {**cleared, "state": _resting_state(marketplace, record), "listing_url": None,
                                            "listing_id": None, "revision_id": None})
    elif state == "listed" and record.get("state") != "published":
        # The seller looked and the listing is there. That is true whether the
        # record was unconfirmed or had already been reset to a resting state
        # after a publish Anteroom could not confirm: the mark is the evidence
        # the machine record was missing, so it becomes live here.
        records.save(conv_id, marketplace, {**cleared, "state": "published", "listing_url": value["url"],
                                            "listing_id": value["listing_id"]})
    elif state != "not_listed" and record.get("state") in UNSETTLED_STATES:
        records.save(conv_id, marketplace, {**cleared, "state": "published"})
    if record.get("job_id") and record.get("state") in UNSETTLED_STATES and JobRepo(db).get(record["job_id"]):
        JobRepo(db).add_event(record["job_id"], "native_marked", None, {"marketplace": marketplace, "mark": state})
    _store(db, conv_id, "marketplaceMarks", marketplace, value)
    # Marking listed or not listed starts the record over; a sale keeps how the listing ended.
    if state != "sold":
        _store(db, conv_id, "marketplaceDelists", marketplace, None)
    if state == "listed":
        from vendoo_studio.services.relay_sales import reconcile_unmatched

        reconcile_unmatched(db, conversation_id=conv_id)
    return listings(db, conv_id)


async def _delete_ebay(item_id: str, record: dict | None = None) -> dict:
    from vendoo_studio.services.ebay_client import EbayClient, EbayFailure

    client = await EbayClient.connect()
    record = record or {}
    group_key = str(record.get("ebay_group_key") or "")
    offers = record.get("ebay_variant_offers") if isinstance(record.get("ebay_variant_offers"), dict) else {}
    if group_key and offers and str(record.get("ebay_listing_id") or "") == item_id:
        # A listing with variations Anteroom made: end the whole group, and keep its offers to list again.
        from vendoo_studio.services.ebay_variations import end_group

        return await end_group(client, group_key, [str(offer_id) for offer_id in offers.values()])
    try:
        await client.trading("EndFixedPriceItem", {"ItemID": item_id, "EndingReason": "NotAvailable"})
    except EbayFailure as exc:
        # 1047: the listing has already ended. Anything else is the seller's to check.
        if "1047" in str(exc):
            return {"ok": True, "state": "deleted", "already": True}
        raise
    return {"ok": True, "state": "deleted"}


async def _delete_etsy(item_id: str) -> dict:
    from vendoo_studio.services.etsy_listings import connected_shop_id

    shop_id = connected_shop_id()
    try:
        remote = await marketplace_accounts.etsy_api("GET", f"listings/{item_id}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {"ok": True, "state": "deleted", "already": True}
        raise
    if str(remote.get("shop_id")) != shop_id:
        raise ValueError("This Etsy listing belongs to another shop. Connect the shop that owns it.")
    if remote.get("state") == "sold_out":
        raise ValueError("This Etsy listing has sold out. It was not deleted.")
    await marketplace_accounts.etsy_api("DELETE", f"listings/{item_id}")
    return {"ok": True, "state": "deleted"}


def _marketplace_message(marketplace: str, exc: Exception) -> str | None:
    if marketplace == "etsy":
        from vendoo_studio.services.etsy_listings import marketplace_message

        return marketplace_message(exc)
    return scrub(getattr(exc, "marketplace_message", None))


def _failure_text(marketplace: str, exc: Exception) -> str:
    from vendoo_studio.services.etsy_listings import _error_text

    if marketplace == "etsy":
        return _error_text(exc)
    if isinstance(exc, browser_bridge.BrowserBridgeError):
        return "Chrome did not confirm the delete. Delist again to check; it is safe to repeat."
    return str(exc) or "The marketplace did not confirm the delete. Delist again to check; it is safe to repeat."


async def delist(db: Session, conv_id: str, marketplaces: list[str], confirm: bool) -> dict:
    """Delete the named listings. Runs as a job holding the automation slot, so no Send starts into Chrome meanwhile."""
    from vendoo_studio.services.extension_connection import extension_manager, schedule_advance_job_queue

    names = list(dict.fromkeys(str(m).strip().lower() for m in marketplaces if str(m or "").strip()))
    if confirm is not True:
        raise DelistError(400, "Confirm the delist before anything is deleted.")
    if not names or any(name not in MARKETPLACES for name in names):
        raise DelistError(400, "Name the marketplaces to delist.")
    if manual := [name for name in names if name in MANUAL_DELIST]:
        label = ", ".join(name.title() for name in manual)
        raise DelistError(409, f"Anteroom can't delete {label} listings yet. Delete it on {label}, then choose Mark as not listed.")
    known = listings(db, conv_id)
    for name in names:
        entry = known.get(name)
        if not entry or not entry["listing_id"]:
            raise DelistError(409, f"Anteroom has no {name} listing link for this item.")
        if entry["sold_here"]:
            raise DelistError(409, f"This item sold on {name}. That listing is never deleted.")
    if BROWSER_MARKETPLACES & set(names) and not extension_manager.connected:
        raise DelistError(409, "Connect Chrome first.")
    repo = JobRepo(db)
    listing = ListingRepo(db).get_current(conv_id)
    with start_gate():
        if repo.get_active():
            raise DelistError(409, "Another automation job is queued or running. Wait for it to finish.")
        job = repo.create(conv_id, listing.current_revision_id if listing else "", {"delist": names},
                          status="dispatched", current_step="native_delist")
        claim_api_job(job.id)
    failed = False
    try:
        for name in names:
            entry = known[name]
            base = {"listing_id": entry["listing_id"], "url": entry["url"], "at": _now()}
            _record(db, conv_id, name, {**base, "state": "deleting"})
            repo.add_event(job.id, "native_progress", "native_delist", {"marketplace": name, "step": "delist", "label": "Delisting"})
            try:
                if name == "ebay":
                    result = await _delete_ebay(entry["listing_id"], MarketplaceListingRepo(db).get(conv_id, "ebay"))
                elif name == "etsy":
                    result = await _delete_etsy(entry["listing_id"])
                else:
                    result = await browser_bridge.request(job, "marketplace.delete", {
                        "marketplace": name, "listing_id": entry["listing_id"], "confirm": True,
                    }, timeout=90)
                if result.get("ok") is True and result.get("state") == "deleted":
                    _record(db, conv_id, name, {**base, "state": "deleted", "error": None, "at": _now()})
                else:
                    failed = True
                    _record(db, conv_id, name, {**base, "state": "failed", "at": _now(),
                                               "error": str(result.get("error") or "The marketplace did not confirm the delete.")[:300],
                                               "marketplace_message": scrub(result.get("marketplace_message"))})
            except Exception as exc:  # noqa: BLE001 - recorded per marketplace for the seller
                failed = True
                _record(db, conv_id, name, {**base, "state": "failed", "at": _now(), "error": _failure_text(name, exc)[:300],
                                           "marketplace_message": _marketplace_message(name, exc)})
        repo.update_status(job.id, "failed" if failed else "completed", "native_delist",
                           error="A delist did not finish." if failed else None)
    except BaseException:
        repo.update_status(job.id, "failed", "native_delist", error="The delist stopped before it finished.")
        raise
    finally:
        release_api_job(job.id)
        schedule_advance_job_queue()
    return listings(db, conv_id)
