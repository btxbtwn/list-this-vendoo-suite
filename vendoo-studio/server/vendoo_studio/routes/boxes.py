from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.services import boxes

router = APIRouter(prefix="/api/boxes", tags=["boxes"])


class BoxTotals(BaseModel):
    spent: float
    listings: int
    listed: int
    sold: int
    returned: float
    profit: float
    roi: float | None
    sell_through: float | None
    unsold_asking: float
    median_days: int | None


class BoxRow(BoxTotals):
    id: str
    store: str
    title: str
    url: str | None
    price: float
    shipping: float
    pieces: int | None
    estimate_per_piece: float | None
    list_shipping: float | None
    bought_at: str | None
    cost_per_piece: float | None


class StoreRow(BoxTotals):
    store: str
    boxes: int


class BoxesResponse(BaseModel):
    boxes: list[BoxRow]
    stores: list[StoreRow]


class BoxCreate(BaseModel):
    store: str = Field(min_length=1)
    title: str = Field(min_length=1)
    price: float = Field(ge=0)
    shipping: float = Field(0, ge=0)
    pieces: int | None = Field(None, ge=0)
    url: str | None = None
    bought_at: datetime | None = None
    estimate_per_piece: float | None = Field(None, ge=0)
    list_shipping: float | None = Field(None, ge=0)


class BoxUpdate(BaseModel):
    store: str | None = Field(None, min_length=1)
    title: str | None = Field(None, min_length=1)
    price: float | None = Field(None, ge=0)
    shipping: float | None = Field(None, ge=0)
    pieces: int | None = Field(None, ge=0)
    url: str | None = None
    bought_at: datetime | None = None


@router.get("", response_model=BoxesResponse)
def list_boxes(db: Session = Depends(get_db)):
    return BoxesResponse.model_validate(boxes.results(db))


@router.post("", response_model=BoxesResponse)
def create_box(body: BoxCreate, db: Session = Depends(get_db)):
    boxes.create_box(db, **body.model_dump())
    return BoxesResponse.model_validate(boxes.results(db))


@router.patch("/{box_id}", response_model=BoxesResponse)
def update_box(box_id: str, body: BoxUpdate, db: Session = Depends(get_db)):
    box = boxes.get_box(db, box_id)
    if box is None:
        raise HTTPException(404, "Box not found")
    boxes.update_box(db, box, body.model_dump(exclude_unset=True))
    return BoxesResponse.model_validate(boxes.results(db))


@router.delete("/{box_id}", response_model=BoxesResponse)
def delete_box(box_id: str, db: Session = Depends(get_db)):
    box = boxes.get_box(db, box_id)
    if box is None:
        raise HTTPException(404, "Box not found")
    boxes.delete_box(db, box)
    return BoxesResponse.model_validate(boxes.results(db))
