from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.services.inventory_analytics import inventory_analytics

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


class AnalyticsInventory(BaseModel):
    active: int
    draft: int
    sold: int
    failed: int
    working: int
    asking_value: float
    cost_value: float
    cost_known: int
    stale_count: int
    stale_value: float
    undated_count: int


class AnalyticsSales(BaseModel):
    count: int
    revenue: float
    profit: float | None
    profit_known: int
    fees_known: int
    revenue_known: int
    days_known: int
    average_price: float | None
    median_days: int | None
    margin: float | None


class AnalyticsPrevious(BaseModel):
    start: str
    end: str
    sales: AnalyticsSales


class AnalyticsPeriod(AnalyticsSales):
    label: str


class AnalyticsGroup(AnalyticsSales):
    id: str
    label: str


class AnalyticsActiveListing(BaseModel):
    conversation_id: str
    title: str
    price: float
    days_listed: int | None


class AnalyticsAging(BaseModel):
    label: str
    count: int
    asking_value: float
    listings: list[AnalyticsActiveListing]


class AnalyticsStaleListing(BaseModel):
    conversation_id: str
    title: str
    days_listed: int
    price: float
    cost: float | None
    lowest_price: int | None
    discount_percent: int | None
    sale_price: float | None


class AnalyticsSale(BaseModel):
    conversation_id: str
    title: str
    price: float | None
    marketplace: str
    sold_at: str | None
    days_listed: int | None
    event: str | None
    profit: float | None


class AnalyticsOldListing(BaseModel):
    conversation_id: str
    title: str
    price: float
    days_listed: int


class AnalyticsResponse(BaseModel):
    range: str
    undated_sales: int
    periods_truncated: bool
    inventory: AnalyticsInventory
    sales: AnalyticsSales
    previous: AnalyticsPrevious | None
    periods: list[AnalyticsPeriod]
    marketplaces: list[AnalyticsGroup]
    categories: list[AnalyticsGroup]
    brands: list[AnalyticsGroup]
    aging: list[AnalyticsAging]
    stale: list[AnalyticsStaleListing]
    recent: list[AnalyticsSale]
    oldest: list[AnalyticsOldListing]


@router.get("", response_model=AnalyticsResponse)
def get_analytics(
    span: str = Query("12m", alias="range"),
    db: Session = Depends(get_db),
):
    try:
        payload = inventory_analytics(db, range_id=span)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unknown analytics range.") from exc
    return AnalyticsResponse.model_validate(payload)
