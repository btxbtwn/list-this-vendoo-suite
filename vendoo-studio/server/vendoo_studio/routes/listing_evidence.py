from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.repositories.queries import ConversationRepo
from vendoo_studio.services import listing_evidence as evidence

router = APIRouter(prefix="/api/conversations/{conv_id}/evidence", tags=["listings"])


def _check(db: Session, conv_id: str) -> None:
    if not ConversationRepo(db).get(conv_id):
        raise HTTPException(404, "Conversation not found")


class ShippingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shipping: evidence.ShippingOutcome | None


@router.get("")
def get_evidence(conv_id: str, db: Session = Depends(get_db)):
    _check(db, conv_id)
    return evidence.get_evidence(db, conv_id)


@router.put("/shipping")
def update_shipping(conv_id: str, body: ShippingUpdate, db: Session = Depends(get_db)):
    _check(db, conv_id)
    evidence.save_shipping(db, conv_id, body.shipping)
    return evidence.get_evidence(db, conv_id)


@router.put("/engagement")
def update_engagement(conv_id: str, body: evidence.EngagementOutcome, db: Session = Depends(get_db)):
    _check(db, conv_id)
    evidence.save_engagement(db, conv_id, body)
    return evidence.get_evidence(db, conv_id)


@router.delete("/engagement")
def delete_engagement(conv_id: str, marketplace: evidence.MARKETPLACES, start_date: date, end_date: date,
                      db: Session = Depends(get_db)):
    _check(db, conv_id)
    evidence.delete_engagement(db, conv_id, marketplace, start_date, end_date)
    return evidence.get_evidence(db, conv_id)
