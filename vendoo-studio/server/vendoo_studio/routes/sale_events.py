from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.services import sale_events

router = APIRouter(prefix="/api/sale-events", tags=["sale-events"])


class EventSale(BaseModel):
    conversation_id: str
    title: str
    price: float | None
    marketplace: str
    sold_at: str | None


class EventRow(BaseModel):
    id: str
    name: str
    starts_on: str
    ends_on: str
    discount_percent: int | None
    marketplaces: list[str]
    status: str
    sold: int
    revenue: float
    per_week: float | None
    before_per_week: float | None
    after_per_week: float | None
    after_days: int
    sales: list[EventSale]


class EventsResponse(BaseModel):
    events: list[EventRow]


class EventCreate(BaseModel):
    name: str = Field(min_length=1)
    starts_on: date
    ends_on: date
    marketplaces: list[str] = Field(default_factory=list)
    discount_percent: int | None = Field(None, ge=1, le=90)


@router.get("", response_model=EventsResponse)
def list_events(db: Session = Depends(get_db)):
    return EventsResponse.model_validate(sale_events.results(db))


@router.post("", response_model=EventsResponse)
def create_event(body: EventCreate, db: Session = Depends(get_db)):
    try:
        sale_events.create_event(db, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return EventsResponse.model_validate(sale_events.results(db))


@router.delete("/{event_id}", response_model=EventsResponse)
def delete_event(event_id: str, db: Session = Depends(get_db)):
    event = sale_events.get_event(db, event_id)
    if event is None:
        raise HTTPException(404, "Sale event not found")
    sale_events.delete_event(db, event)
    return EventsResponse.model_validate(sale_events.results(db))
