"""Promotion records only. None of these routes call Vendoo or marketplaces."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.models.sale_event import SaleEvent
from vendoo_studio.services import sale_calendar

router = APIRouter(prefix="/api/analytics/calendar", tags=["analytics"])


def _event(db, event_id: str):
    event = db.get(SaleEvent, event_id)
    if event is None:
        raise HTTPException(404, "Sale event not found.")
    return event


@router.get("")
def get_calendar(timezone: str = Query("UTC", max_length=100), db: Session = Depends(get_db)):
    try:
        return sale_calendar.calendar_data(db, timezone)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("", status_code=201)
def create_event(body: sale_calendar.SalePlan, db: Session = Depends(get_db)):
    try:
        event = sale_calendar.save_plan(db, body)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"id": event.id}


@router.put("/{event_id}")
def edit_event(event_id: str, body: sale_calendar.SalePlan, db: Session = Depends(get_db)):
    try:
        event = sale_calendar.save_plan(db, body, _event(db, event_id))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"id": event.id}


@router.post("/records", status_code=201)
def record_event(body: sale_calendar.SaleRecord, db: Session = Depends(get_db)):
    try:
        event = sale_calendar.save_record(db, body)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"id": event.id}


@router.put("/records/{event_id}")
def edit_record(event_id: str, body: sale_calendar.SaleRecord, db: Session = Depends(get_db)):
    try:
        event = sale_calendar.save_record(db, body, _event(db, event_id))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"id": event.id}


class StatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["planned", "ran", "cancelled"]


@router.patch("/{event_id}/status")
def update_status(event_id: str, body: StatusUpdate, db: Session = Depends(get_db)):
    try:
        sale_calendar.change_status(db, _event(db, event_id), body.status)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True}


@router.delete("/{event_id}")
def delete_event(event_id: str, db: Session = Depends(get_db)):
    db.delete(_event(db, event_id))
    db.commit()
    return {"ok": True}
