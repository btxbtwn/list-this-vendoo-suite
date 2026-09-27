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


class AnalyticsSales(BaseModel):
    count: int
    revenue: float
    profit: float | None
    profit_known: int
    average_price: float | None
    median_days: int | None


class AnalyticsPeriod(BaseModel):
    label: str
    count: int
    revenue: float


class AnalyticsGroup(BaseModel):
    id: str
    label: str
    count: int
    revenue: float


class AnalyticsAging(BaseModel):
    label: str
    count: int
    asking_value: float


class AnalyticsSale(BaseModel):
    conversation_id: str
    title: str
    price: float
    marketplace: str
    sold_at: str | None
    days_listed: int | None


class AnalyticsResponse(BaseModel):
    range: str
    undated_sales: int
    periods_truncated: bool
    inventory: AnalyticsInventory
    sales: AnalyticsSales
    periods: list[AnalyticsPeriod]
    marketplaces: list[AnalyticsGroup]
    categories: list[AnalyticsGroup]
    brands: list[AnalyticsGroup]
    aging: list[AnalyticsAging]
    recent: list[AnalyticsSale]


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
