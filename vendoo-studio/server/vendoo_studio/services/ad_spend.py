"""Poshmark Promoted Closet and Etsy Ads spend, set against what sold.

Neither programme has an API Studio can read, and Vendoo does not import ad
charges, so the seller copies each dashboard's figures for a stretch of days:
what was spent, and optionally the clicks, orders, and revenue the dashboard
attributes to the ads. Analytics spreads each entry's spend evenly over its
days, so a range that covers part of an entry carries that part of its cost.
Nothing here calls Vendoo or a marketplace.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from vendoo_studio.models.ad_spend import AdSpend

AdMarketplace = Literal["poshmark", "etsy"]
AD_MARKETPLACES = ("poshmark", "etsy")


class AdSpendEntry(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid", str_strip_whitespace=True)

    marketplace: AdMarketplace
    start_date: date
    end_date: date
    spend: float = Field(ge=0, le=1_000_000)
    clicks: int | None = Field(default=None, ge=0)
    orders: int | None = Field(default=None, ge=0)
    revenue: float | None = Field(default=None, ge=0, le=10_000_000)
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def valid_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after the start date.")
        return self


def list_entries(db: Session) -> list[AdSpend]:
    return db.query(AdSpend).order_by(AdSpend.end_date.desc(), AdSpend.created_at.desc()).all()


def save_entry(db: Session, entry: AdSpendEntry, row: AdSpend | None = None) -> AdSpend:
    row = row or AdSpend()
    for key, value in entry.model_dump().items():
        setattr(row, key, value)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def entry_view(row: AdSpend) -> dict[str, Any]:
    return {
        "id": row.id,
        "marketplace": row.marketplace,
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat(),
        "spend": row.spend,
        "clicks": row.clicks,
        "orders": row.orders,
        "revenue": row.revenue,
        "notes": row.notes or "",
        "roas": _ratio(row.revenue, row.spend),
        "cost_per_click": _ratio(row.spend, row.clicks),
    }


def summarize_ads(
    entries: list[AdSpend],
    *,
    start: datetime | None,
    marketplace_revenue: dict[str, float],
    profit: float | None,
) -> dict[str, Any]:
    """Ad totals for the range beginning ``start`` (None for all time).

    ``marketplace_revenue`` is each marketplace's recorded sales revenue in the
    same range, so spend can be read as a share of everything that sold there,
    not only the sales the dashboard credits to the ads.
    """
    first = start.date() if start is not None else None
    totals = {market: _empty() for market in AD_MARKETPLACES}
    for row in entries:
        share = _share(row.start_date, row.end_date, first)
        if share <= 0:
            continue
        bucket = totals.setdefault(row.marketplace, _empty())
        bucket["entries"] += 1
        bucket["spend"] += row.spend * share
        for key in ("clicks", "orders", "revenue"):
            value = getattr(row, key)
            if value is not None:
                bucket[key] = (bucket[key] or 0.0) + value * share
    markets = [
        _market_view(market, bucket, marketplace_revenue.get(market, 0.0))
        for market, bucket in totals.items()
        if bucket["entries"]
    ]
    spend = sum(market["spend"] for market in markets)
    return {
        "spend": _money(spend),
        "profit_after_ads": _money(profit - spend) if profit is not None else None,
        "marketplaces": markets,
    }


def _share(first_day: date, last_day: date, window_start: date | None) -> float:
    """The part of an entry's days that fall on or after ``window_start``."""
    days = (last_day - first_day).days + 1
    if window_start is None or first_day >= window_start:
        return 1.0
    if last_day < window_start:
        return 0.0
    return ((last_day - window_start).days + 1) / days


def _empty() -> dict[str, Any]:
    return {"entries": 0, "spend": 0.0, "clicks": None, "orders": None, "revenue": None}


def _market_view(market: str, bucket: dict[str, Any], sales_revenue: float) -> dict[str, Any]:
    spend = bucket["spend"]
    return {
        "id": market,
        "entries": bucket["entries"],
        "spend": _money(spend),
        "clicks": _count(bucket["clicks"]),
        "orders": _count(bucket["orders"]),
        "revenue": _money(bucket["revenue"]) if bucket["revenue"] is not None else None,
        "roas": _ratio(bucket["revenue"], spend),
        "cost_per_click": _ratio(spend, bucket["clicks"]),
        "sales_revenue": _money(sales_revenue),
        "spend_percent": round(spend / sales_revenue * 100, 1) if sales_revenue else None,
    }


def _ratio(top: float | None, bottom: float | None) -> float | None:
    if top is None or not bottom:
        return None
    return round(top / bottom, 2)


def _count(value: float | None) -> int | None:
    return round(value) if value is not None else None


def _money(value: float) -> float:
    return round(float(value), 2)
