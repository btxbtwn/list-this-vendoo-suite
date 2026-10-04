"""Sales and inventory totals from the imported Vendoo workspace.

The sidebar already knows status, price, and dates. Analytics also needs the
sold price, cost, brand, and category, which live on the current listing and
in the Vendoo notes. This reads those columns and nothing else, then groups
them. It does not call Vendoo.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vendoo_studio.services.sale_events import EventWindow

ANALYTICS_RANGES = ("30d", "90d", "12m", "all")
_RECENT = 8
_MAX_MONTHS = 18
_MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)
_BUSY = {"in_progress", "listing", "failed"}
_VENDOO_STATUSES = {"sold", "active", "draft"}
_AGING = (
    ("Under 2 weeks", 0, 14),
    ("2–4 weeks", 14, 30),
    ("1–2 months", 30, 60),
    ("2–3 months", 60, 90),
    ("Over 3 months", 90, None),
)
# Listings this old with no sale get a deeper cut than the everyday event one.
STALE_DAYS = 60
EVENT_PERCENT = 25
# Deepest first; the first that still covers the item's cost after fees wins.
DEEP_PERCENTS = (40, 35)
# With no cost recorded there is no floor to check, so stay at the shallower cut.
UNKNOWN_COST_PERCENT = 35


@dataclass(frozen=True)
class AnalyticsItem:
    """One listing, reduced to the figures the page can show."""

    conversation_id: str
    title: str
    status: str
    price: float
    cost: float | None
    brand: str
    category: str
    sold_price: float | None
    sold_at: datetime | None
    listed_at: datetime | None
    marketplace: str
    days_listed: int | None
    fees: float | None = None
    shipping_cost: float = 0.0
    shipping_credit: float = 0.0
    box_id: str | None = None

    @property
    def has_cost(self) -> bool:
        return self.cost is not None

    @property
    def net(self) -> float:
        """What the sale brought in before the item's own cost."""
        return (
            (self.sold_price or 0.0) + self.shipping_credit
            - (self.fees or 0.0) - self.shipping_cost
        )

    @property
    def profit(self) -> float:
        """Vendoo's net profit: sold price plus shipping paid, less the rest."""
        return self.net - (self.cost or 0.0)


def inventory_analytics(
    db,
    *,
    range_id: str = "12m",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Totals for ``range_id`` (``30d``, ``90d``, ``12m``, or ``all``)."""
    if range_id not in ANALYTICS_RANGES:
        raise ValueError(range_id)
    from vendoo_studio.services.sale_events import windows

    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    return summarize(load_rows(db), range_id=range_id, now=clock, events=windows(db))


def load_rows(db) -> list[AnalyticsItem]:
    """Every listing as an analytics row. Current revision only."""
    from sqlalchemy import func

    from vendoo_studio.models.conversation import Conversation
    from vendoo_studio.models.listing import Listing, ListingRevision
    from vendoo_studio.models.sourcing import SourceBox
    from vendoo_studio.services.sell_through import _days_between, _parse_moment
    from vendoo_studio.services.vendoo_import import VENDOO_MARKETPLACE_ALIASES, parse_notes

    facets = {
        conv_id: (price, cost, brand, category)
        for conv_id, price, cost, brand, category in (
            db.query(
                Listing.conversation_id,
                func.json_extract(ListingRevision.listing_json, "$.price"),
                func.json_extract(ListingRevision.listing_json, "$.cost"),
                func.json_extract(ListingRevision.listing_json, "$.brand"),
                func.json_extract(ListingRevision.listing_json, "$.category_path"),
            )
            .join(ListingRevision, ListingRevision.id == Listing.current_revision_id)
            .all()
        )
    }
    # An item with no cost of its own carries its share of the box it came from.
    box_share = {
        box_id: _money((price + shipping) / pieces)
        for box_id, price, shipping, pieces in db.query(
            SourceBox.id, SourceBox.price, SourceBox.shipping, SourceBox.pieces,
        ).all()
        if pieces
    }
    rows: list[AnalyticsItem] = []
    conversations = db.query(
        Conversation.id,
        Conversation.title,
        Conversation.status,
        Conversation.notes,
        Conversation.box_id,
    ).all()
    for conv_id, title, status, notes_raw, box_id in conversations:
        notes = parse_notes(notes_raw)
        price, cost, brand, category = facets.get(conv_id, (None, None, None, None))
        dates = notes.get("vendooDates") if isinstance(notes.get("vendooDates"), dict) else {}
        sale = notes.get("vendooSale") if isinstance(notes.get("vendooSale"), dict) else {}
        listed_text = str(dates.get("listed") or "")
        sold_text = str(dates.get("sold") or sale.get("soldAt") or "")
        effective = _effective_status(str(status or ""), notes)
        sold_price = _amount(sale.get("price"))
        asking = _number(price)
        sale_cost = _amount(sale.get("cost"))
        own_cost = sale_cost if sale_cost is not None else _amount(cost)
        rows.append(AnalyticsItem(
            conversation_id=conv_id,
            title=(str(title or "").strip() or "Untitled listing"),
            status=effective,
            price=asking,
            cost=own_cost if own_cost is not None else box_share.get(box_id),
            brand=str(brand or "").strip(),
            category=_category_label(category),
            sold_price=sold_price,
            sold_at=_parse_moment(sold_text),
            listed_at=_parse_moment(listed_text),
            marketplace=_marketplace(sale, dates, notes, VENDOO_MARKETPLACE_ALIASES),
            days_listed=_days_between(listed_text, sold_text),
            fees=_amount(sale.get("fees")),
            shipping_cost=_amount(sale.get("shippingCost")) or 0.0,
            shipping_credit=_amount(sale.get("shippingCredit")) or 0.0,
            box_id=box_id,
        ))
    return rows


def summarize(
    items: list[AnalyticsItem],
    *,
    range_id: str,
    now: datetime,
    events: list[EventWindow] | None = None,
) -> dict[str, Any]:
    """Group already-loaded rows. ``now`` keeps the window testable."""
    start = _window_start(range_id, now)
    include_undated = range_id == "all"
    sales = [
        item for item in items
        if item.status == "sold" and _in_window(item, start, now, include_undated=include_undated)
    ]
    dated = [item for item in sales if item.sold_at is not None]
    buckets, truncated = _buckets(range_id, now, [item.sold_at for item in dated if item.sold_at])
    period_sales: list[list[AnalyticsItem]] = [[] for _ in buckets]
    for item in dated:
        index = _place(item.sold_at, buckets) if item.sold_at is not None else None
        if index is not None:
            period_sales[index].append(item)

    previous = None
    if start is not None:
        previous_start = start - (now - start)
        previous_sales = [
            item for item in items
            if item.status == "sold" and item.sold_at is not None
            and previous_start <= item.sold_at < start
        ]
        previous = {
            "start": previous_start.isoformat(),
            "end": start.isoformat(),
            "sales": _sales_stats(previous_sales),
        }
    return {
        "range": range_id,
        "undated_sales": sum(1 for item in items if item.status == "sold" and item.sold_at is None),
        "periods_truncated": truncated,
        "inventory": _inventory(items, now),
        "sales": _sales_stats(sales),
        "previous": previous,
        "periods": [
            {"label": label, **_sales_stats(rows)}
            for (_, _, label), rows in zip(buckets, period_sales, strict=True)
        ],
        "marketplaces": _ranked_groups(_groups(sales, _marketplace_key)),
        "categories": _ranked_groups(_groups(sales, _category_key)),
        "brands": _ranked_groups(_groups(sales, _brand_key)),
        "aging": _aging(items, now),
        "stale": _stale(items, now),
        "recent": _recent(sales, events or []),
        "oldest": _oldest(items, now),
    }


def _sales_stats(sales: list[AnalyticsItem]) -> dict[str, Any]:
    priced = [item for item in sales if item.sold_price is not None]
    revenue = sum(item.sold_price or 0.0 for item in priced)
    profit_rows = [item for item in priced if item.cost is not None]
    days = [item.days_listed for item in sales if item.days_listed is not None]
    profit = sum(item.profit for item in profit_rows)
    known_revenue = sum(item.sold_price or 0.0 for item in profit_rows)
    return {
        "count": len(sales),
        "revenue": _money(revenue),
        "revenue_known": len(priced),
        "profit": _money(profit) if profit_rows else None,
        "profit_known": len(profit_rows),
        "fees_known": sum(1 for item in profit_rows if item.fees is not None),
        "average_price": _money(revenue / len(priced)) if priced else None,
        "median_days": _median_days(days),
        "days_known": len(days),
        "margin": round(profit / known_revenue * 100, 1) if known_revenue else None,
    }


def _effective_status(status: str, notes: dict) -> str:
    """Vendoo's label, unless Studio is mid-send or the last send failed."""
    if status in _BUSY:
        return status
    vendoo = str(notes.get("vendooStatus") or "")
    if vendoo in _VENDOO_STATUSES:
        return vendoo
    return status or "draft"


def _marketplace(sale: dict, dates: dict, notes: dict, aliases: dict[str, str]) -> str:
    raw = str(sale.get("marketplace") or "").strip()
    if not raw:
        sold_by = dates.get("soldByMarketplace")
        if isinstance(sold_by, dict) and sold_by:
            raw = max(sold_by, key=lambda market: str(sold_by.get(market) or ""))
    if not raw:
        listed = notes.get("vendooMarketplaces")
        if isinstance(listed, list) and len(listed) == 1:
            raw = str(listed[0] or "").strip()
    market = aliases.get(raw, raw)
    if not market or market in {"general", "validate"}:
        return "unknown"
    return market


def _category_label(value: Any) -> str:
    if isinstance(value, list):
        parts = [str(part).strip() for part in value if str(part).strip()]
        return parts[-1] if parts else ""
    text = str(value or "").strip()
    if text.startswith("["):
        import json
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return _category_label(parsed)
    if ">" in text:
        return text.split(">")[-1].strip()
    return text


def _inventory(items: list[AnalyticsItem], now: datetime) -> dict[str, Any]:
    counts = {"active": 0, "draft": 0, "sold": 0, "failed": 0, "working": 0}
    asking = 0.0
    for item in items:
        if item.status == "active":
            counts["active"] += 1
            asking += item.price
        elif item.status == "sold":
            counts["sold"] += 1
        elif item.status == "failed":
            counts["failed"] += 1
        elif item.status in {"in_progress", "listing"}:
            counts["working"] += 1
        else:
            counts["draft"] += 1
    counts["asking_value"] = _money(asking)
    active = [item for item in items if item.status == "active"]
    stale = [item for item in active if item.listed_at and (now - item.listed_at).days >= 90]
    counts["cost_value"] = _money(sum(item.cost or 0.0 for item in active if item.has_cost))
    counts["cost_known"] = sum(item.has_cost for item in active)
    counts["stale_count"] = len(stale)
    counts["stale_value"] = _money(sum(item.price for item in stale))
    counts["undated_count"] = sum(item.listed_at is None for item in active)
    return counts


def _groups(sales: list[AnalyticsItem], key_of):
    groups: dict[str, tuple[str, list[AnalyticsItem]]] = {}
    for item in sales:
        key, label = key_of(item)
        if not key:
            continue
        if key not in groups:
            groups[key] = (label, [])
        groups[key][1].append(item)
    return {
        key: {"id": key, "label": label, **_sales_stats(rows)}
        for key, (label, rows) in groups.items()
    }


def _marketplace_key(item: AnalyticsItem) -> tuple[str, str]:
    return item.marketplace, item.marketplace


def _category_key(item: AnalyticsItem) -> tuple[str, str]:
    label = item.category.strip()
    return label.casefold(), label


def _brand_key(item: AnalyticsItem) -> tuple[str, str]:
    label = item.brand.strip()
    return label.casefold(), label


def _ranked_groups(groups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = sorted(
        groups.values(),
        key=lambda row: (-row["revenue"], -row["count"], str(row["label"]).lower()),
    )
    return [
        {**row, "revenue": _money(row["revenue"])}
        for row in rows
    ]


def _aging(items: list[AnalyticsItem], now: datetime) -> list[dict[str, Any]]:
    buckets = [
        {"label": label, "count": 0, "asking_value": 0.0, "listings": []}
        for label, _start, _end in _AGING
    ]
    undated = {"label": "No list date", "count": 0, "asking_value": 0.0, "listings": []}
    for item in items:
        if item.status != "active":
            continue
        days = None
        bucket = undated
        if item.listed_at is not None:
            days = max(0, int((now - item.listed_at).total_seconds() // 86_400))
            for index, (_label, start, end) in enumerate(_AGING):
                if days >= start and (end is None or days < end):
                    bucket = buckets[index]
                    break
        bucket["count"] += 1
        bucket["asking_value"] += item.price
        bucket["listings"].append({
            "conversation_id": item.conversation_id,
            "title": item.title,
            "price": _money(item.price),
            "days_listed": days,
        })
    return [
        {**row, "asking_value": _money(row["asking_value"]),
         "listings": sorted(row["listings"], key=lambda item: (-(item["days_listed"] or 0), item["title"]))}
        for row in [*buckets, undated] if row["count"]
    ]


def lowest_price(cost: float | None) -> int | None:
    """The whole-dollar price that still returns the item's cost after fees."""
    from vendoo_studio.services.scout import FEES

    if not cost or cost <= 0:
        return None
    return math.ceil(cost / (1 - FEES))


def deep_discount(price: float, floor: int | None) -> int | None:
    """The deepest cut that stays at or above ``floor``, or None when even the
    everyday event discount would sell this item at a loss."""
    if floor is None:
        return UNKNOWN_COST_PERCENT
    for percent in (*DEEP_PERCENTS, EVENT_PERCENT):
        if price * (1 - percent / 100) >= floor:
            return percent
    return None


def _stale(items: list[AnalyticsItem], now: datetime) -> list[dict[str, Any]]:
    """Active listings past ``STALE_DAYS``, oldest first, with how deep to cut."""
    rows = []
    for item in items:
        if item.status != "active" or item.listed_at is None or item.price <= 0:
            continue
        days = int((now - item.listed_at).total_seconds() // 86_400)
        if days < STALE_DAYS:
            continue
        floor = lowest_price(item.cost)
        percent = deep_discount(item.price, floor)
        rows.append({
            "conversation_id": item.conversation_id,
            "title": item.title,
            "days_listed": days,
            "price": _money(item.price),
            "cost": _money(item.cost) if item.cost is not None else None,
            "lowest_price": floor,
            "discount_percent": percent,
            "sale_price": _money(item.price * (1 - percent / 100)) if percent is not None else None,
        })
    return sorted(rows, key=lambda row: (-row["days_listed"], row["title"]))


def _recent(sales: list[AnalyticsItem], events: list[EventWindow]) -> list[dict[str, Any]]:
    ordered = sorted(
        sales,
        key=lambda item: item.sold_at or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return [
        {
            "conversation_id": item.conversation_id,
            "title": item.title,
            "price": _money(item.sold_price) if item.sold_price is not None else None,
            "marketplace": item.marketplace,
            "sold_at": item.sold_at.isoformat() if item.sold_at else None,
            "days_listed": item.days_listed,
            "event": next((event.name for event in events if event.covers(item)), None),
            "profit": _money(item.profit) if item.has_cost and item.sold_price is not None else None,
        }
        for item in ordered[:_RECENT]
    ]


def _oldest(items: list[AnalyticsItem], now: datetime) -> list[dict[str, Any]]:
    """Oldest active listings worth reviewing; never mutate or send them."""
    stale = [
        item for item in items
        if item.status == "active" and item.listed_at is not None
        and (now - item.listed_at).days >= 90
    ]
    stale.sort(key=lambda item: (item.listed_at, -item.price, item.conversation_id))
    return [{
        "conversation_id": item.conversation_id,
        "title": item.title,
        "price": _money(item.price),
        "days_listed": (now - item.listed_at).days,
    } for item in stale[:_RECENT]]


def _window_start(range_id: str, now: datetime) -> datetime | None:
    """Start of the range. Twelve months follows the chart's calendar months."""
    if range_id == "12m":
        year, month = _add_months(now.year, now.month, -11)
        return datetime(year, month, 1, tzinfo=UTC)
    days = {"30d": 30, "90d": 90}.get(range_id)
    if days is None:
        return None
    return now - timedelta(days=days)


def _in_window(
    item: AnalyticsItem, start: datetime | None, end: datetime, *, include_undated: bool,
) -> bool:
    if item.sold_at is None:
        return include_undated
    return item.sold_at <= end and (start is None or item.sold_at >= start)


def _buckets(
    range_id: str,
    now: datetime,
    dated: list[datetime],
) -> tuple[list[tuple[datetime, datetime, str]], bool]:
    if range_id == "30d":
        return _span_buckets(now, days=30, count=6), False
    if range_id == "90d":
        return _span_buckets(now, days=90, count=6), False
    if range_id == "12m":
        return _month_buckets(now, 12), False
    if not dated:
        return [], False
    earliest = min(dated)
    start_index = earliest.year * 12 + (earliest.month - 1)
    end_index = now.year * 12 + (now.month - 1)
    count = max(1, end_index - start_index + 1)
    truncated = count > _MAX_MONTHS
    return _month_buckets(now, min(count, _MAX_MONTHS)), truncated


def _span_buckets(now: datetime, *, days: int, count: int):
    start = now - timedelta(days=days)
    step = (now - start) / count
    buckets = []
    for index in range(count):
        bucket_start = start + step * index
        bucket_end = now if index == count - 1 else start + step * (index + 1)
        buckets.append((bucket_start, bucket_end, f"{bucket_start.month}/{bucket_start.day}"))
    return buckets


def _month_buckets(now: datetime, count: int):
    buckets = []
    for offset in range(count - 1, -1, -1):
        year, month = _add_months(now.year, now.month, -offset)
        start = datetime(year, month, 1, tzinfo=UTC)
        next_year, next_month = _add_months(year, month, 1)
        end = datetime(next_year, next_month, 1, tzinfo=UTC)
        label = _MONTHS[month - 1]
        if year != now.year:
            label = f"{label} '{year % 100:02d}"
        buckets.append((start, end, label))
    return buckets


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _place(moment: datetime, buckets) -> int | None:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    for index, (start, end, _label) in enumerate(buckets):
        last = index == len(buckets) - 1
        if moment >= start and (moment < end or (last and moment <= end)):
            return index
    return None


def _median_days(values: list[int]) -> int | None:
    if not values:
        return None
    return int(round(statistics.median(values)))


def _number(value: Any) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(amount) or amount <= 0:
        return 0.0
    return amount


def _amount(value: Any) -> float | None:
    """A recorded sale amount, where zero is a real figure and absent is None."""
    if value is None or value == "":
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(amount) or amount < 0:
        return None
    return amount


def _money(value: float) -> float:
    return round(float(value), 2)
