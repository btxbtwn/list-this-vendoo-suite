from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from vendoo_studio.services import box_scout

router = APIRouter(prefix="/api/sourcing", tags=["sourcing"])


class SourcingComp(BaseModel):
    url: str
    title: str
    sold_at: str
    price: float
    marketplace: str
    snippet: str
    # Set when the sale is the seller's own listing rather than a web result.
    conversation_id: str | None = None


class SourcingActiveComp(BaseModel):
    url: str
    title: str
    price: float
    marketplace: str
    snippet: str


class SourcingLot(BaseModel):
    store: str
    variant_id: int | str  # Shopify variant number, or a marketplace lot id
    title: str
    url: str
    price: float
    compare_at: float | None
    pcs: int
    pcs_estimated: bool
    grade: str
    lbs: float
    lbs_estimated: bool
    vip: bool
    listed: str | None
    seller_resale: float | None
    theme: str
    # Marketplace lots: who sells it and the state it ships from; shipping may be in the price.
    seller: str | None = None
    origin: str | None = None
    free_shipping: bool = False
    checkout_fee: float = 0.0
    ship_est: float
    ship_list: float
    usable_pcs: float
    demand: float
    trend_hits: list[str]
    landed: float
    cog_per_pc: float
    cog_per_usable_pc: float
    resale_per_pc: float | None
    # The seller's own sales from this store against the estimates; 1 until known.
    resale_factor: float = 1.0
    sell_through: float
    expected_revenue: float | None
    expected_profit: float | None
    roi: float | None
    score: float
    comps_count: int
    research_at: str | None
    research_source: str | None
    active_median: float | None
    resale_low: float | None
    operating_cost: float
    break_even_pcs: int | None
    downside_profit: float | None


class SourcingEvidence(BaseModel):
    theme: str
    per_piece: float
    sold_median: float
    active_median: float | None
    low: float
    high: float
    comps: list[SourcingComp]
    active: list[SourcingActiveComp]
    updated_at: str | None
    source: str | None


class SourcingCart(BaseModel):
    store: str
    name: str
    subtotal: float
    shipping: float
    free_shipping: bool
    free_shipping_over: float | None
    # Whether the link opens a cart with the boxes in it, or the first box's own page.
    cart_fills: bool
    cart_url: str
    lots: list[SourcingLot]


class SourcingBuyList(BaseModel):
    budget: float
    total: float
    expected_profit: float
    carts: list[SourcingCart]
    exclusions: dict[str, str]


class SourcingStore(BaseModel):
    name: str
    error: str | None
    sellout: float | None
    zone: int | None
    # Ship-from locations with a zone: 1 for a warehouse, the seller states for a marketplace.
    origins: int = 1


class SourcingShippingCalibration(BaseModel):
    factor: float | None
    orders: int
    needed: int


class SourcingShipping(BaseModel):
    residential_surcharge: float
    fuel_surcharge_pct: float
    fuel_surcharge_as_of: str
    factors: dict[str, float]
    calibration: dict[str, SourcingShippingCalibration]


class SourcingVipUpside(BaseModel):
    boxes: int
    extra_profit: float
    monthly_fee: float


class SourcingAssumptions(BaseModel):
    sell_through: float
    fees: float
    grade_yield: dict[str, float]
    cost_per_piece: float


class SourcingCalibration(BaseModel):
    factor: float | None
    sales: int
    needed: int


class SourcingWindow(BaseModel):
    buy_on: str
    start_date: str
    end_date: str
    ready_in_weeks: int
    selling_window_weeks: int
    market: str
    timezone: str


class SourcingHistoricalExample(BaseModel):
    title: str
    sold_at: str
    sold_price: float
    listing_source: str


class SourcingHistoricalGroup(BaseModel):
    category_path: str
    item_type: str | None
    count: int
    historical_median_price: float
    period_counts: dict[str, int]
    examples: list[SourcingHistoricalExample]


class SourcingHistory(BaseModel):
    periods: list[dict[str, str]]
    dated_recorded_sales: int
    matching_window_sales: int
    excluded_incomplete_or_invalid: int
    minimum_group_sales: int
    groups: list[SourcingHistoricalGroup]
    coverage: str


class SourcingSeasonality(BaseModel):
    window: SourcingWindow
    seller_history: SourcingHistory


class SourcingSnapshot(BaseModel):
    updated_at: str
    destination_zip: str
    preferences: dict[str, str | float | bool]
    stores: dict[str, SourcingStore]
    research: bool
    priced_themes: int
    shipping: SourcingShipping
    assumptions: SourcingAssumptions
    buy_list: SourcingBuyList
    store_buy_lists: dict[str, SourcingBuyList]
    lots: list[SourcingLot]
    calibration: dict[str, SourcingCalibration] = {}
    seasonality: SourcingSeasonality
    vip_upside: SourcingVipUpside | None


class SourcingPrefs(BaseModel):
    budget: float
    min_roi: float
    raghouse_vip: bool
    zip: str
    recent_zips: list[str]
    sell_through: float
    fees: float
    cost_per_piece: float
    ready_in_weeks: int
    selling_window_weeks: int


class SourcingTrend(BaseModel):
    terms: list[str]
    updated_at: str | None
    source: str | None


class SourcingResponse(BaseModel):
    refreshing: bool
    research_available: bool
    prefs: SourcingPrefs
    trend: SourcingTrend
    snapshot: SourcingSnapshot | None


class SourcingPrefsUpdate(BaseModel):
    budget: float | None = Field(None, gt=0, allow_inf_nan=False)
    min_roi: float | None = Field(None, ge=0, allow_inf_nan=False)
    sell_through: float | None = Field(None, gt=0, le=1, allow_inf_nan=False)
    fees: float | None = Field(None, ge=0, lt=1, allow_inf_nan=False)
    cost_per_piece: float | None = Field(None, ge=0, allow_inf_nan=False)
    ready_in_weeks: int | None = Field(None, ge=0, le=26, strict=True)
    selling_window_weeks: int | None = Field(None, ge=1, le=26, strict=True)
    raghouse_vip: bool | None = None
    zip: str | None = Field(None, pattern=r"^\d{5}$")


def _response() -> SourcingResponse:
    state = box_scout.read_state()
    return SourcingResponse(
        refreshing=box_scout.refreshing(),
        research_available=box_scout.research_available(),
        prefs=SourcingPrefs.model_validate(state["prefs"]),
        trend=SourcingTrend.model_validate(state["trend"]),
        snapshot=SourcingSnapshot.model_validate(state["snapshot"]) if state["snapshot"] else None,
    )


@router.get("", response_model=SourcingResponse)
def get_sourcing():
    if box_scout.refresh_is_due():
        box_scout.refresh_in_background()
    return _response()


@router.get("/evidence", response_model=SourcingEvidence)
def get_sourcing_evidence(theme: str = Query(min_length=1)):
    entry = box_scout.evidence(theme)
    if entry is None:
        raise HTTPException(status_code=404, detail="No current sold evidence for this kind of box.")
    return SourcingEvidence.model_validate(entry)


@router.post("/refresh", response_model=SourcingResponse)
def refresh_sourcing():
    box_scout.refresh_in_background()
    return _response()


@router.put("/prefs", response_model=SourcingResponse)
def update_sourcing_prefs(update: SourcingPrefsUpdate):
    try:
        box_scout.set_prefs(**update.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Rebuild for the saved costs and selling window using the last store crawl.
    box_scout.refresh_in_background(recrawl=False)
    return _response()
