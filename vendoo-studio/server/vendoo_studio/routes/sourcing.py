from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from vendoo_studio.services.box_scout import ScoutUnavailable, scout_boxes

router = APIRouter(prefix="/api/sourcing", tags=["sourcing"])


class ScoutShipping(BaseModel):
    destination_zip: str
    zone: int
    residential_surcharge: float
    fuel_surcharge_pct: float
    fuel_surcharge_as_of: str
    ship_factor: float


class ScoutBox(BaseModel):
    title: str
    url: str
    price: float
    compare_at: float | None
    pcs: int
    grade: str
    lbs: float
    ship_est: float
    landed: float
    cog_per_pc: float
    cog_per_usable_pc: float
    demand: float
    trend_hits: list[str]
    vip: bool
    lot_date: str | None
    score: float


class ScoutResponse(BaseModel):
    fetched_at: str
    baseline_sellout: float
    sellout_days: int
    matched: int
    shipping: ScoutShipping
    boxes: list[ScoutBox]


@router.get("/raghouse", response_model=ScoutResponse)
def get_raghouse_boxes(
    trend: str = "",
    min_pcs: int = Query(20, ge=1),
    max_pcs: int = Query(0, ge=0),
    target_cog: float = Query(2.0, gt=0),
    max_cog: float = Query(4.0, gt=0),
    max_price: float = Query(0, ge=0),
    include_vip: bool = True,
    limit: int = Query(50, ge=1, le=500),
    refresh: bool = False,
):
    try:
        payload = scout_boxes(
            trend=trend,
            min_pcs=min_pcs,
            max_pcs=max_pcs,
            target_cog=target_cog,
            max_cog=max_cog,
            max_price=max_price,
            include_vip=include_vip,
            limit=limit,
            refresh=refresh,
        )
    except ScoutUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ScoutResponse.model_validate(payload)
