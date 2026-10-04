"""Wholesale boxes the seller bought, and what came of them.

A box is recorded when it is bought, usually straight from a Sourcing buy-list
row, and the listings made from it point at it. That is enough to answer the
question the buy list exists for: was the box worth it? Money in is the box
price plus its shipping; money back is what each sale brought in after fees and
shipping, read from the same rows Analytics uses.

An item with no cost of goods of its own carries the box's cost divided by its
piece count, both in Analytics and on the Vendoo form.
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from vendoo_studio.models.conversation import Conversation
from vendoo_studio.models.sourcing import SourceBox
from vendoo_studio.services.inventory_analytics import AnalyticsItem, load_rows

_LISTED = {"active", "sold"}
# Sales from bought boxes before a store's resale estimates are adjusted, and
# how far they may move: a few lucky or unlucky sales should not swing the list.
CALIBRATION_MIN_SALES = 5
CALIBRATION_RANGE = (0.3, 2.0)


def list_boxes(db: Session) -> list[SourceBox]:
    return db.query(SourceBox).order_by(SourceBox.bought_at.desc(), SourceBox.created_at.desc()).all()


def get_box(db: Session, box_id: str) -> SourceBox | None:
    return db.get(SourceBox, box_id)


def create_box(
    db: Session,
    *,
    store: str,
    title: str,
    price: float,
    shipping: float = 0.0,
    pieces: int | None = None,
    url: str | None = None,
    bought_at: datetime | None = None,
    estimate_per_piece: float | None = None,
) -> SourceBox:
    box = SourceBox(
        store=store.strip(),
        title=title.strip(),
        price=price,
        shipping=shipping,
        pieces=pieces or None,
        estimate_per_piece=estimate_per_piece or None,
        url=(url or "").strip() or None,
        bought_at=bought_at or datetime.now(UTC),
    )
    db.add(box)
    db.commit()
    db.refresh(box)
    return box


def update_box(db: Session, box: SourceBox, changes: dict[str, Any]) -> SourceBox:
    for key, value in changes.items():
        if key in {"store", "title"} and isinstance(value, str):
            value = value.strip()
        if key == "url":
            value = (value or "").strip() or None
        if key == "pieces":
            value = value or None
        setattr(box, key, value)
    db.commit()
    db.refresh(box)
    return box


def delete_box(db: Session, box: SourceBox) -> None:
    """Forget the box. Its listings stay; they just no longer belong to a box."""
    db.query(Conversation).filter(Conversation.box_id == box.id).update({Conversation.box_id: None})
    db.delete(box)
    db.commit()


def assign_box(db: Session, conv: Conversation, box_id: str | None) -> None:
    if box_id and get_box(db, box_id) is None:
        raise LookupError(box_id)
    conv.box_id = box_id or None


def cost_share(box: SourceBox | None) -> float | None:
    """One piece's share of what the box cost, delivered."""
    if box is None or not box.pieces:
        return None
    return round((box.price + box.shipping) / box.pieces, 2)


def results(db: Session) -> dict[str, Any]:
    """Every box with what it has returned so far, and the same per store."""
    boxes = list_boxes(db)
    items_by_box: dict[str, list[AnalyticsItem]] = {}
    for item in load_rows(db):
        if item.box_id:
            items_by_box.setdefault(item.box_id, []).append(item)
    rows = [_box_row(box, items_by_box.get(box.id, [])) for box in boxes]
    stores: dict[str, list[tuple[SourceBox, list[AnalyticsItem]]]] = {}
    for box in boxes:
        stores.setdefault(box.store, []).append((box, items_by_box.get(box.id, [])))
    return {
        "boxes": rows,
        "stores": [_store_row(name, entries) for name, entries in sorted(stores.items())],
    }


def resale_calibration(db: Session) -> dict[str, dict[str, Any]]:
    """Per store, what pieces from bought boxes sold for against the estimate the
    buy list used when the box was bought. The median ratio becomes the store's
    factor once there are enough sales to trust it."""
    estimates = {
        box.id: (box.store, box.estimate_per_piece)
        for box in list_boxes(db)
        if box.estimate_per_piece
    }
    ratios: dict[str, list[float]] = {}
    for item in load_rows(db):
        if item.status != "sold" or not item.sold_price or item.box_id not in estimates:
            continue
        store, estimate = estimates[item.box_id]
        ratios.setdefault(store, []).append(item.sold_price / estimate)
    low, high = CALIBRATION_RANGE
    return {
        store: {
            "factor": (
                round(min(high, max(low, statistics.median(values))), 2)
                if len(values) >= CALIBRATION_MIN_SALES else None
            ),
            "sales": len(values),
            "needed": CALIBRATION_MIN_SALES,
        }
        for store, values in ratios.items()
    }


def _box_row(box: SourceBox, items: list[AnalyticsItem]) -> dict[str, Any]:
    return {
        "id": box.id,
        "store": box.store,
        "title": box.title,
        "url": box.url,
        "price": round(box.price, 2),
        "shipping": round(box.shipping, 2),
        "pieces": box.pieces,
        "estimate_per_piece": box.estimate_per_piece,
        "bought_at": _iso(box.bought_at),
        "cost_per_piece": cost_share(box),
        **_totals(box.price + box.shipping, box.pieces, items),
    }


def _store_row(store: str, entries: list[tuple[SourceBox, list[AnalyticsItem]]]) -> dict[str, Any]:
    spent = sum(box.price + box.shipping for box, _items in entries)
    known_pieces = [box.pieces for box, _items in entries]
    pieces = sum(known_pieces) if all(known_pieces) else None
    items = [item for _box, box_items in entries for item in box_items]
    return {"store": store, "boxes": len(entries), **_totals(spent, pieces, items)}


def _totals(spent: float, pieces: int | None, items: list[AnalyticsItem]) -> dict[str, Any]:
    sold = [item for item in items if item.status == "sold"]
    returned = sum(item.net for item in sold)
    days = [item.days_listed for item in sold if item.days_listed is not None]
    return {
        "spent": round(spent, 2),
        "listings": len(items),
        "listed": sum(1 for item in items if item.status in _LISTED),
        "sold": len(sold),
        "returned": round(returned, 2),
        "profit": round(returned - spent, 2),
        "roi": round((returned - spent) / spent, 3) if spent > 0 else None,
        # Of the pieces in the box when the count is known, else of the listings made.
        "sell_through": round(len(sold) / (pieces or len(items)), 3) if (pieces or items) else None,
        "unsold_asking": round(sum(item.price for item in items if item.status == "active"), 2),
        "median_days": int(statistics.median(days)) if days else None,
    }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()
