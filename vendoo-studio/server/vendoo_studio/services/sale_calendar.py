"""Local promotion planning and descriptive sales patterns; no marketplace writes."""
from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from vendoo_studio.models.conversation import Conversation
from vendoo_studio.models.sale_event import SaleEvent
from vendoo_studio.services.inventory_analytics import AnalyticsItem, load_rows
from vendoo_studio.services.vendoo_import import parse_notes

Marketplace = Literal["ebay", "depop", "etsy"]
EventStatus = Literal["planned", "ran", "cancelled"]
MARKETPLACES = ("ebay", "depop", "etsy")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Choose a valid time zone.") from exc


class SaleRecord(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=120)
    marketplace: str = Field(min_length=1, max_length=40)
    start_date: date
    end_date: date
    timezone: str = Field(max_length=100)
    discount_percent: float | None = Field(default=None, ge=0, le=95)
    notes: str = Field(default="", max_length=2000)

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        zone(value)
        return value

    @model_validator(mode="after")
    def valid_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after the start date.")
        return self


class SalePlan(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=120)
    marketplace: Marketplace
    start_date: date
    end_date: date
    timezone: str = Field(max_length=100)
    discount_percent: float = Field(ge=5, le=75)
    fee_percent: float = Field(ge=0, le=50)
    shipping_cost: float = Field(ge=0, le=10000)
    minimum_profit: float = Field(ge=0, le=100000)
    item_ids: list[str] = Field(min_length=1, max_length=1000)
    notes: str = Field(default="", max_length=2000)

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        zone(value)
        return value

    @model_validator(mode="after")
    def valid_dates_and_items(self):
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after the start date.")
        if (self.end_date - self.start_date).days > 89:
            raise ValueError("Plan a sale lasting at most 90 days.")
        if len(set(self.item_ids)) != len(self.item_ids):
            raise ValueError("Choose each item once.")
        return self


def eligible_items(db, rows: list[AnalyticsItem]) -> list[dict]:
    markets = {
        cid: parse_notes(notes).get("vendooMarketplaces", [])
        for cid, notes in db.query(Conversation.id, Conversation.notes).all()
    }
    result = []
    for row in rows:
        listed = markets.get(row.conversation_id)
        if row.status != "active" or not isinstance(listed, list):
            continue
        supported = [market for market in MARKETPLACES if market in listed]
        if not supported or not math.isfinite(row.price) or row.price <= 0:
            continue
        cost = row.cost if row.cost is not None and math.isfinite(row.cost) else None
        result.append({
            "id": row.conversation_id, "title": row.title, "price": row.price,
            "cost": cost, "category": row.category, "marketplaces": supported,
            "listed_at": row.listed_at.isoformat() if row.listed_at else None,
        })
    return sorted(result, key=lambda item: (item["listed_at"] or "9999", item["title"]))


def estimated_profit(item: dict, plan: SalePlan) -> float | None:
    if item["cost"] is None:
        return None
    # Round the sale price first, as a marketplace would, then estimate costs.
    price = (Decimal(str(item["price"])) * (1 - Decimal(str(plan.discount_percent)) / 100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP,
    )
    profit = price * (1 - Decimal(str(plan.fee_percent)) / 100) - Decimal(str(item["cost"])) - Decimal(str(plan.shipping_cost))
    return float(profit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _check_overlap(db, marketplace, start_date, end_date, item_ids, event):
    existing = db.query(SaleEvent).filter(
        SaleEvent.marketplace == marketplace,
        SaleEvent.status != "cancelled",
        SaleEvent.start_date <= end_date,
        SaleEvent.end_date >= start_date,
    ).all()
    for other in existing:
        if event is not None and other.id == event.id:
            continue
        if item_ids & {item["id"] for item in other.items}:
            raise ValueError("These items are already in an overlapping sale on this marketplace.")


def save_plan(db, plan: SalePlan, event: SaleEvent | None = None) -> SaleEvent:
    if event is not None and event.status != "planned":
        raise ValueError("Only planned events can be edited.")
    available = {item["id"]: item for item in eligible_items(db, load_rows(db))}
    chosen = []
    for item_id in plan.item_ids:
        item = available.get(item_id)
        if item is None or plan.marketplace not in item["marketplaces"]:
            raise ValueError("An item is no longer active on this marketplace. Refresh the calendar.")
        profit = estimated_profit(item, plan)
        if profit is None:
            raise ValueError(f"Add a cost for {item['title']} before including it in a sale.")
        if profit < plan.minimum_profit:
            raise ValueError(f"{item['title']} falls below your minimum estimated profit.")
        chosen.append({**item, "estimated_profit": profit})
    _check_overlap(db, plan.marketplace, plan.start_date, plan.end_date, set(plan.item_ids), event)
    target = event or SaleEvent()
    for key, value in plan.model_dump(exclude={"item_ids"}).items():
        setattr(target, key, value)
    target.items = chosen
    if event is None:
        target.status = "planned"
        db.add(target)
    db.commit()
    db.refresh(target)
    return target


def save_record(db, record: SaleRecord, event: SaleEvent | None = None, *, now: datetime | None = None):
    if record.marketplace not in MARKETPLACES and (event is None or record.marketplace != event.marketplace):
        raise ValueError("Choose eBay, Depop, or Etsy for a new sale record.")
    today = (now or datetime.now(UTC)).astimezone(zone(record.timezone)).date()
    if record.start_date > today:
        raise ValueError("Record a sale once it has started. Use a plan for future events.")
    if event is not None and event.items:
        raise ValueError("This is an item-level plan, not a marketplace-wide record.")
    target = event or SaleEvent(items=[])
    target.status = "ran"
    for key, value in record.model_dump().items():
        setattr(target, key, value)
    if event is None:
        db.add(target)
    db.commit()
    db.refresh(target)
    return target


def change_status(db, event: SaleEvent, status: EventStatus, *, now: datetime | None = None):
    today = (now or datetime.now(UTC)).astimezone(zone(event.timezone)).date()
    if status == "ran" and event.start_date > today:
        raise ValueError("Mark an event as run once its start date has arrived.")
    if event.status == "cancelled" and status != "cancelled":
        _check_overlap(db, event.marketplace, event.start_date, event.end_date, {item["id"] for item in event.items}, event)
    event.status = status
    db.commit()


def weekday_patterns(rows: list[AnalyticsItem], timezone: str, *, now: datetime) -> list[dict]:
    """Rank two-day windows over up to 26 complete weeks of imported history.

    Sample thresholds gate suggestions, not statistical confidence. With no
    inventory/traffic history, this is a descriptive pattern to test.
    """
    tz = zone(timezone)
    today = now.astimezone(tz).date()
    end = today - timedelta(days=today.weekday())  # exclude the current partial week
    result = []
    for market in MARKETPLACES:
        sales = [row for row in rows if row.status == "sold" and row.marketplace == market
                 and row.sold_at is not None and row.sold_at <= now]
        first = min((row.sold_at.astimezone(tz).date() for row in sales), default=end)
        # Exclude the earliest partial week; dates before first recorded sale
        # cannot be treated as evidence of no sales.
        first_monday = first + timedelta(days=(-first.weekday()) % 7)
        start = max(first_monday, end - timedelta(weeks=26))
        weeks = max(0, (end - start).days // 7)
        counts = [0] * 7
        for row in sales:
            sold_day = row.sold_at.astimezone(tz).date()
            if start <= sold_day < end:
                counts[sold_day.weekday()] += 1
        total = sum(counts)
        enough = weeks >= 8 and total >= 20
        windows = [counts[i] + counts[(i + 1) % 7] for i in range(7)]
        best = max(range(7), key=lambda i: windows[i])
        # Don't invent a preferred window when the observed days tie.
        suggestion = enough and windows.count(windows[best]) == 1
        next_start = today + timedelta(days=(best - today.weekday()) % 7)
        result.append({
            "marketplace": market, "weeks": weeks, "sales": total,
            "history_start": start.isoformat(), "history_end": (end - timedelta(days=1)).isoformat(),
            "weekdays": [{"label": label, "count": counts[i],
                          "average": round(counts[i] / weeks, 2) if weeks else None}
                         for i, label in enumerate(WEEKDAYS)],
            "suggested_start": next_start.isoformat() if suggestion else None,
            "suggested_end": (next_start + timedelta(days=1)).isoformat() if suggestion else None,
            "reason": (
                f"{WEEKDAYS[best]}–{WEEKDAYS[(best + 1) % 7]} had {windows[best]} of {total} "
                f"imported sales across {weeks} complete weeks. Try this window and measure the result."
                if suggestion else
                "No clear preferred window in your weekday pattern." if enough else
                "Need at least 20 dated sales spanning 8 complete weeks on this marketplace."
            ),
        })
    return result


def _totals(rows: list[AnalyticsItem]) -> dict:
    priced = [row for row in rows if row.sold_price is not None]
    known = [row for row in priced if row.cost is not None and row.fees is not None]
    return {"count": len(rows), "revenue": round(sum(row.sold_price for row in priced), 2),
            "revenue_known": len(priced),
            "profit": round(sum(row.profit for row in known), 2) if len(known) == len(rows) else None,
            "profit_known": len(known)}


def event_result(event: SaleEvent, events: list[SaleEvent], rows: list[AnalyticsItem], *, now: datetime):
    if event.status != "ran":
        return None
    tz = zone(event.timezone)
    end = min(event.end_date, now.astimezone(tz).date())
    if end < event.start_date:
        return None
    sales = [(row, row.sold_at.astimezone(tz).date()) for row in rows
             if row.status == "sold" and (event.marketplace == "all" or row.marketplace == event.marketplace)
             and row.sold_at is not None and row.sold_at <= now]
    ids = {item["id"] for item in event.items}
    during = [row for row, day in sales if event.start_date <= day <= end]
    selected = [row for row in during if not ids or row.conversation_id in ids]
    # Whole-week shift matches weekdays and puts the entire baseline before sale.
    shift = timedelta(weeks=math.ceil(((end - event.start_date).days + 1) / 7))
    before_start, before_end = event.start_date - shift, end - shift
    overlaps = any(other.id != event.id and other.status == "ran"
                   and (other.marketplace == event.marketplace or "all" in {other.marketplace, event.marketplace})
                   and other.start_date <= before_end and other.end_date >= before_start
                   for other in events)
    prior = [row for row, day in sales if before_start <= day <= before_end]
    earliest = min((day for _, day in sales), default=end)
    baseline_reason = ("Another recorded promotion overlaps the comparison period." if overlaps else
                       "Imported sales history does not reach the comparison period."
                       if earliest > before_start else None)
    after_days = max(0, min(14, (now.astimezone(tz).date() - event.end_date).days))
    after_end = event.end_date + timedelta(days=after_days)
    after = [row for row, day in sales if event.end_date < day <= after_end]
    return {
        "after_days": after_days, "after": _totals(after) if after_days else None,
        "through": end.isoformat(), "scope": "items" if ids else "marketplace", "selected": _totals(selected),
        "marketplace": _totals(during),
        "comparison": None if baseline_reason else _totals(prior),
        "comparison_start": before_start.isoformat(), "comparison_end": before_end.isoformat(),
        "comparison_unavailable": baseline_reason,
        "ongoing": end < event.end_date,
    }


def event_view(event: SaleEvent, events: list[SaleEvent], rows: list[AnalyticsItem], *, now: datetime):
    keys = ("id", "title", "marketplace", "start_date", "end_date", "timezone",
            "discount_percent", "fee_percent", "shipping_cost", "minimum_profit", "items", "status", "notes")
    return {**{key: getattr(event, key) for key in keys},
            "result": event_result(event, events, rows, now=now)}


def calendar_data(db, timezone: str, *, now: datetime | None = None):
    clock = now or datetime.now(UTC)
    zone(timezone)
    rows = load_rows(db)
    events = db.query(SaleEvent).order_by(SaleEvent.start_date, SaleEvent.created_at).all()
    return {
        "timezone": timezone,
        "events": [event_view(event, events, rows, now=clock) for event in events],
        "items": eligible_items(db, rows),
        "patterns": weekday_patterns(rows, timezone, now=clock),
    }
