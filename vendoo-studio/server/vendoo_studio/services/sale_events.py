"""Marketplace sale events the seller joined, and whether they moved sales.

An event is a name, a first and last day, and the marketplaces it ran on. A
sale on one of those marketplaces between those days is an event sale; nothing
has to be tagged by hand. Each event is set against the weeks before it and
the two weeks after, so the seller can see whether the discount bought sales
or only gave margin away.

Days are the seller's calendar days, so a sale is placed by its local date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from vendoo_studio.models.sale_event import SaleEvent
from vendoo_studio.services.inventory_analytics import AnalyticsItem, load_rows

# The baseline an event is measured against: long enough that one lucky week
# does not set it, short enough to still describe the shop as it is now.
BEFORE_DAYS = 28
# Whether the boost outlasted the event.
AFTER_DAYS = 14


@dataclass(frozen=True)
class EventWindow:
    """The part of an event that decides which sales belong to it."""

    name: str
    starts_on: date
    ends_on: date
    marketplaces: frozenset[str]

    def covers(self, item: AnalyticsItem) -> bool:
        if item.status != "sold" or item.sold_at is None:
            return False
        if self.marketplaces and item.marketplace not in self.marketplaces:
            return False
        return self.starts_on <= local_day(item.sold_at) <= self.ends_on


def local_day(moment: datetime) -> date:
    """The seller's calendar day for a sale; Studio runs on the seller's Mac."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone().date()


def window(event: SaleEvent) -> EventWindow:
    return EventWindow(
        name=event.name,
        starts_on=event.starts_on,
        ends_on=event.ends_on,
        marketplaces=frozenset(event.marketplaces or []),
    )


def list_events(db: Session) -> list[SaleEvent]:
    return db.query(SaleEvent).order_by(SaleEvent.starts_on.desc(), SaleEvent.created_at.desc()).all()


def windows(db: Session) -> list[EventWindow]:
    return [window(event) for event in list_events(db)]


def get_event(db: Session, event_id: str) -> SaleEvent | None:
    return db.get(SaleEvent, event_id)


def create_event(
    db: Session,
    *,
    name: str,
    starts_on: date,
    ends_on: date,
    marketplaces: list[str],
    discount_percent: int | None = None,
) -> SaleEvent:
    if ends_on < starts_on:
        raise ValueError("The last day is before the first day.")
    event = SaleEvent(
        name=name.strip(),
        starts_on=starts_on,
        ends_on=ends_on,
        marketplaces=sorted({market.strip() for market in marketplaces if market.strip()}),
        discount_percent=discount_percent or None,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def delete_event(db: Session, event: SaleEvent) -> None:
    db.delete(event)
    db.commit()


def results(db: Session, *, today: date | None = None) -> dict[str, Any]:
    items = load_rows(db)
    day = today or datetime.now().date()
    return {"events": [event_row(event, items, today=day) for event in list_events(db)]}


def event_row(event: SaleEvent, items: list[AnalyticsItem], *, today: date) -> dict[str, Any]:
    span = window(event)
    during = [item for item in items if span.covers(item)]
    run_days = (span.ends_on - span.starts_on).days + 1
    if today < span.starts_on:
        status, observed = "upcoming", 0
    elif today <= span.ends_on:
        status, observed = "running", (today - span.starts_on).days + 1
    else:
        status, observed = "ended", run_days

    before = _span(span, span.starts_on - timedelta(days=BEFORE_DAYS), span.starts_on - timedelta(days=1))
    after_days = max(0, min(AFTER_DAYS, (today - span.ends_on).days))
    after_end = span.ends_on + timedelta(days=after_days)
    after = _span(span, span.ends_on + timedelta(days=1), after_end)
    ordered = sorted(during, key=lambda item: item.sold_at or datetime.min.replace(tzinfo=UTC), reverse=True)
    return {
        "id": event.id,
        "name": event.name,
        "starts_on": span.starts_on.isoformat(),
        "ends_on": span.ends_on.isoformat(),
        "discount_percent": event.discount_percent,
        "marketplaces": sorted(span.marketplaces),
        "status": status,
        "sold": len(during),
        "revenue": round(sum(item.sold_price or 0.0 for item in during), 2),
        "per_week": _per_week(len(during), observed),
        "before_per_week": _per_week(_count(items, before), BEFORE_DAYS),
        "after_per_week": _per_week(_count(items, after), after_days),
        "after_days": after_days,
        "sales": [
            {
                "conversation_id": item.conversation_id,
                "title": item.title,
                "price": round(item.sold_price, 2) if item.sold_price is not None else None,
                "marketplace": item.marketplace,
                "sold_at": item.sold_at.isoformat() if item.sold_at else None,
            }
            for item in ordered
        ],
    }


def _span(event: EventWindow, start: date, end: date) -> EventWindow:
    """The same marketplaces over other days, for the before and after rates."""
    return EventWindow(name=event.name, starts_on=start, ends_on=end, marketplaces=event.marketplaces)


def _count(items: list[AnalyticsItem], span: EventWindow) -> int:
    if span.ends_on < span.starts_on:
        return 0
    return sum(1 for item in items if span.covers(item))


def _per_week(count: int, days: int) -> float | None:
    if days <= 0:
        return None
    return round(count / days * 7, 1)
