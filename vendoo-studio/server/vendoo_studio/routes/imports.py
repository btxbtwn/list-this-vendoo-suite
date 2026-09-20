from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.services import vendoo_bulk_import
from vendoo_studio.services.vendoo_import import import_vendoo_item, vendoo_binding

router = APIRouter(prefix="/api/imports", tags=["imports"])


class VendooImportRequest(BaseModel):
    item_id: str
    url: str | None = None
    source: str | None = None
    item: dict | None = None
    form: dict | None = None
    image_urls: list[str] | None = None


class VendooImportResponse(BaseModel):
    ok: bool
    conversation_id: str
    job_id: str | None = None
    reused: bool
    photo_count: int
    photo_warnings: list[str] = []
    listing_title: str


@router.post("/vendoo", response_model=VendooImportResponse)
async def import_vendoo_listing(body: VendooImportRequest, db: Session = Depends(get_db)):
    item_id = (body.item_id or "").strip()
    if not item_id or item_id.lower() in {"new", "edit", "create"}:
        raise HTTPException(400, "Open a saved Vendoo listing first.")
    if not body.item and not body.form:
        raise HTTPException(400, "No Vendoo listing data was provided.")

    result = await import_vendoo_item(
        db,
        item_id=item_id,
        item=body.item,
        form=body.form,
        url=body.url,
        source=body.source,
        image_urls=body.image_urls,
    )
    conv = result["conversation"]
    binding = vendoo_binding(conv.notes)
    return VendooImportResponse(
        ok=True,
        conversation_id=conv.id,
        job_id=result["job"].id,
        reused=result["reused"],
        photo_count=result["photo_count"],
        photo_warnings=result["photo_warnings"],
        listing_title=str(result["listing"].get("title") or binding.get("vendooItemId") or "Imported listing"),
    )


@router.post("/vendoo/bulk")
async def start_bulk_import():
    """Import every item in the seller's Vendoo inventory, photos on demand."""
    try:
        return vendoo_bulk_import.start()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/vendoo/bulk")
def bulk_import_status():
    return vendoo_bulk_import.status()


@router.post("/vendoo/bulk/cancel")
def cancel_bulk_import():
    return {"ok": vendoo_bulk_import.cancel(), **vendoo_bulk_import.status()}


@router.post("/vendoo/labels")
async def start_label_sync():
    """Re-read draft / active / sold for every bound listing from Vendoo's inventory."""
    from vendoo_studio.services import vendoo_label_sync

    return vendoo_label_sync.start()


@router.get("/vendoo/labels")
def label_sync_status():
    from vendoo_studio.services import vendoo_label_sync

    return vendoo_label_sync.status()
