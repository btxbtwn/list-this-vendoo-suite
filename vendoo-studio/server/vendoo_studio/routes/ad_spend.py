"""Ad spend entries only. None of these routes call Vendoo or marketplaces."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.models.ad_spend import AdSpend
from vendoo_studio.services import ad_spend

router = APIRouter(prefix="/api/analytics/ads", tags=["analytics"])


def _entry(db, entry_id: str) -> AdSpend:
    row = db.get(AdSpend, entry_id)
    if row is None:
        raise HTTPException(404, "Ad spend entry not found.")
    return row


@router.get("")
def list_ads(db: Session = Depends(get_db)):
    return [ad_spend.entry_view(row) for row in ad_spend.list_entries(db)]


@router.post("", status_code=201)
def create_ad(body: ad_spend.AdSpendEntry, db: Session = Depends(get_db)):
    return ad_spend.entry_view(ad_spend.save_entry(db, body))


@router.put("/{entry_id}")
def edit_ad(entry_id: str, body: ad_spend.AdSpendEntry, db: Session = Depends(get_db)):
    return ad_spend.entry_view(ad_spend.save_entry(db, body, _entry(db, entry_id)))


@router.delete("/{entry_id}")
def delete_ad(entry_id: str, db: Session = Depends(get_db)):
    db.delete(_entry(db, entry_id))
    db.commit()
    return {"ok": True}
