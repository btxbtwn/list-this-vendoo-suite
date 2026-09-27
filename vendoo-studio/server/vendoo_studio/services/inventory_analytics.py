"""Sales and inventory totals from the imported Vendoo workspace.

The sidebar already knows status, price, and dates. Analytics also needs the
sold price, cost, brand, and category, which live on the current listing and
in the Vendoo notes. This reads those columns and nothing else, then groups
them. It does not call Vendoo.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

ANALYTICS_RANGES = ("30d", "90d", "12m", "all")
_TOP = 6
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


@dataclass(frozen=True)
class AnalyticsItem:
    """One listing, reduced to the figures the page can show."""

    conversation_id: str
    title: str
    status: str
    price: float
    cost: float
    brand: str
    category: str
    sold_price: float
    sold_at: datetime | None
    listed_at: datetime | None
    marketplace: str
    days_listed: int | None


def inventory_analytics(
    db,
    *,
    range_id: str = "12m",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Totals for ``range_id`` (``30d``, ``90d``, ``12m``, or ``all``)."""
    if range_id not in ANALYTICS_RANGES:
        raise ValueError(range_id)
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    return summarize(load_rows(db), range_id=range_id, now=clock)


def load_rows(db) -> list[AnalyticsItem]:
    """Every listing as an analytics row. Current revision only."""
    from sqlalchemy import func

    from vendoo_studio.models.conversation import Conversation
    from vendoo_studio.models.listing import Listing, ListingRevision
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
    rows: list[AnalyticsItem] = []
    conversations = db.query(
        Conversation.id,
        Conversation.title,
        Conversation.status,
        Conversation.notes,
    ).all()
    for conv_id, title, status, notes_raw in conversations:
        notes = parse_notes(notes_raw)
        price, cost, brand, category = facets.get(conv_id, (None, None, None, None))
        dates = notes.get("vendooDates") if isinstance(notes.get("vendooDates"), dict) else {}
        sale = notes.get("vendooSale") if isinstance(notes.get("vendooSale"), dict) else {}
        listed_text = str(dates.get("listed") or "")
        sold_text = str(dates.get("sold") or sale.get("soldAt") or "")
        effective = _effective_status(str(status or ""), notes)
        sold_price = _number(sale.get("price"))
        asking = _number(price)
        if sold_price <= 0 and effective == "sold":
            sold_price = asking
        rows.append(AnalyticsItem(
            conversation_id=conv_id,
            title=(str(title or "").strip() or "Untitled listing"),
            status=effective,
            price=asking,
            cost=_number(cost),
            brand=str(brand or "").strip(),
            category=_category_label(category),
            sold_price=sold_price,
            sold_at=_parse_moment(sold_text),
            listed_at=_parse_moment(listed_text),
            marketplace=_marketplace(sale, dates, notes, VENDOO_MARKETPLACE_ALIASES),
            days_listed=_days_between(listed_text, sold_text),
        ))
    return rows


def summarize(
    items: list[AnalyticsItem],
    *,
    range_id: str,
    now: datetime,
) -> dict[str, Any]:
    """Group already-loaded rows. ``now`` keeps the window testable."""
    start = _window_start(range_id, now)
    include_undated = range_id == "all"
    sales = [
        item for item in items
        if item.status == "sold" and _in_window(item, start, include_undated=include_undated)
    ]
    dated = [item for item in sales if item.sold_at is not None]
    buckets, truncated = _buckets(range_id, now, [item.sold_at for item in dated if item.sold_at])
    periods = [{"label": label, "count": 0, "revenue": 0.0} for _start, _end, label in buckets]
    for item in dated:
        index = _place(item.sold_at, buckets) if item.sold_at is not None else None
        if index is None:
            continue
        periods[index]["count"] += 1
        periods[index]["revenue"] += item.sold_price

    revenue = sum(item.sold_price for item in sales)
    profit_rows = [item for item in sales if item.cost > 0 and item.sold_price > 0]
    days = [item.days_listed for item in sales if item.days_listed is not None]
    return {
        "range": range_id,
        "undated_sales": sum(1 for item in items if item.status == "sold" and item.sold_at is None),
        "periods_truncated": truncated,
        "inventory": _inventory(items),
        "sales": {
            "count": len(sales),
            "revenue": _money(revenue),
            "profit": _money(sum(item.sold_price - item.cost for item in profit_rows)) if profit_rows else None,
            "profit_known": len(profit_rows),
            "average_price": _money(revenue / len(sales)) if sales else None,
            "median_days": _median_days(days),
        },
        "periods": [
            {**period, "revenue": _money(period["revenue"])}
            for period in periods
        ],
        "marketplaces": _top(_groups(sales, _marketplace_key)),
        "categories": _top(_groups(sales, _category_key)),
        "brands": _top(_groups(sales, _brand_key)),
        "aging": _aging(items, now),
        "recent": _recent(sales),
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


def _inventory(items: list[AnalyticsItem]) -> dict[str, Any]:
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
    return counts


def _groups(sales: list[AnalyticsItem], key_of):
    groups: dict[str, dict[str, Any]] = {}
    for item in sales:
        key, label = key_of(item)
        if not key:
            continue
        row = groups.get(key)
        if row is None:
            groups[key] = {"id": key, "label": label, "count": 1, "revenue": item.sold_price}
            continue
        row["count"] += 1
        row["revenue"] += item.sold_price
    return groups


def _marketplace_key(item: AnalyticsItem) -> tuple[str, str]:
    return item.marketplace, item.marketplace


def _category_key(item: AnalyticsItem) -> tuple[str, str]:
    label = item.category.strip()
    return label.casefold(), label


def _brand_key(item: AnalyticsItem) -> tuple[str, str]:
    label = item.brand.strip()
    return label.casefold(), label


def _top(groups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = sorted(
        groups.values(),
        key=lambda row: (-row["revenue"], -row["count"], str(row["label"]).lower()),
    )
    return [
        {**row, "revenue": _money(row["revenue"])}
        for row in rows[:_TOP]
    ]


def _aging(items: list[AnalyticsItem], now: datetime) -> list[dict[str, Any]]:
    buckets = [
        {"label": label, "count": 0, "asking_value": 0.0}
        for label, _start, _end in _AGING
    ]
    undated = {"label": "No list date", "count": 0, "asking_value": 0.0}
    for item in items:
        if item.status != "active":
            continue
        if item.listed_at is None:
            undated["count"] += 1
            undated["asking_value"] += item.price
            continue
        days = max(0, int((now - item.listed_at).total_seconds() // 86_400))
        for index, (_label, start, end) in enumerate(_AGING):
            if days >= start and (end is None or days < end):
                buckets[index]["count"] += 1
                buckets[index]["asking_value"] += item.price
                break
    rows = [row for row in buckets if row["count"]]
    if undated["count"]:
        rows.append(undated)
    return [
        {**row, "asking_value": _money(row["asking_value"])}
        for row in rows
    ]


def _recent(sales: list[AnalyticsItem]) -> list[dict[str, Any]]:
    ordered = sorted(
        sales,
        key=lambda item: item.sold_at or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return [
        {
            "conversation_id": item.conversation_id,
            "title": item.title,
            "price": _money(item.sold_price),
            "marketplace": item.marketplace,
            "sold_at": item.sold_at.isoformat() if item.sold_at else None,
            "days_listed": item.days_listed,
        }
        for item in ordered[:_RECENT]
    ]


def _window_start(range_id: str, now: datetime) -> datetime | None:
    """Start of the range. Twelve months follows the chart's calendar months."""
    if range_id == "12m":
        year, month = _add_months(now.year, now.month, -11)
        return datetime(year, month, 1, tzinfo=UTC)
    days = {"30d": 30, "90d": 90}.get(range_id)
    if days is None:
        return None
    return now - timedelta(days=days)


def _in_window(item: AnalyticsItem, start: datetime | None, *, include_undated: bool) -> bool:
    if item.sold_at is None:
        return include_undated
    if start is None:
        return True
    return item.sold_at >= start


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
    if amount != amount or amount <= 0:
        return 0.0
    return amount


def _money(value: float) -> float:
    return round(float(value), 2)
