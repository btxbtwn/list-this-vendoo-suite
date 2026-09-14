from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services.vendoo_import import (
    download_vendoo_photos,
    image_urls_from_vendoo,
    listing_from_vendoo,
    merge_notes,
    vendoo_binding,
)

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

    listing = listing_from_vendoo(body.item, body.form)
    url = (body.url or "").strip() or f"https://web.vendoo.co/app/item/{item_id}"
    conv_repo = ConversationRepo(db)
    listing_repo = ListingRepo(db)

    conv = conv_repo.find_by_vendoo_item_id(item_id)
    reused = conv is not None
    if conv is None:
        conv = conv_repo.create(title=listing.get("title") or "Imported from Vendoo")

    conv.notes = merge_notes(conv.notes, {
        "vendooItemId": item_id,
        "vendooUrl": url,
    })
    db.commit()
    db.refresh(conv)

    current = listing_repo.get_current(conv.id)
    revision = listing_repo.save_revision(
        conv_id=conv.id,
        listing_json=listing,
        source="vendoo_import",
        parent_revision_id=current.current_revision_id if current else None,
    )
    conv_repo.add_message(
        conv.id,
        "system",
        f"{'Re-imported' if reused else 'Imported'} from Vendoo item {item_id}.",
    )

    photo_warnings: list[str] = []
    existing_photos = conv_repo.get_photos(conv.id)
    if existing_photos:
        photo_count = len(existing_photos)
    else:
        urls = image_urls_from_vendoo(body.item, body.form, body.image_urls)
        imported = await download_vendoo_photos(urls)
        for meta in imported:
            conv_repo.add_photo(
                conv_id=conv.id,
                original_filename=meta["original_filename"],
                stored_filename=meta["stored_filename"],
                mime_type=meta["mime_type"],
                size_bytes=meta["size_bytes"],
                checksum=meta.get("checksum"),
                width=meta.get("width"),
                height=meta.get("height"),
            )
        photo_count = len(imported)
        if urls and photo_count < len(urls):
            photo_warnings.append(
                f"Imported {photo_count} of {len(urls)} photos. Add missing photos before sending if needed."
            )
        elif not urls:
            photo_warnings.append("No photos were found on the Vendoo listing.")

    from vendoo_studio.repositories.queries import JobRepo
    job_repo = JobRepo(db)
    job = job_repo.create(
        conv_id=conv.id,
        approved_revision_id=revision.id,
        listing_snapshot=listing,
        vendoo_item_id=item_id,
        vendoo_url=url,
        status="imported",
        current_step="imported",
    )
    job_repo.add_event(job.id, "imported", "imported")
    job_repo.save_vendoo_draft(
        job.id,
        item=body.item,
        form=body.form,
        item_id=item_id,
        url=url,
        source=(body.source or "import"),
        step="imported",
    )
    conv_repo.update_status(conv.id, "draft")

    binding = vendoo_binding(conv.notes)
    return VendooImportResponse(
        ok=True,
        conversation_id=conv.id,
        job_id=job.id,
        reused=reused,
        photo_count=photo_count,
        photo_warnings=photo_warnings,
        listing_title=str(listing.get("title") or binding.get("vendooItemId") or "Imported listing"),
    )
