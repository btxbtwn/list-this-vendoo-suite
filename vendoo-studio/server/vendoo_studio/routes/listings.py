from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.models.validation import validate_listing
from vendoo_studio.repositories.queries import ListingRepo, ConversationRepo

router = APIRouter(tags=["listings"])

CORRUPT_SPECIFIC_KEYS = (
    "ebay_specifics",
    "depop_specifics",
    "etsy_specifics",
    "poshmark_specifics",
    "mercari_specifics",
)


def _first_error(validation) -> str:
    for err in validation.errors:
        message = err.get("message") or ""
        if message:
            return message
    return "Listing is invalid"


def _reject_corrupt_listing(listing: dict) -> None:
    if not isinstance(listing, dict):
        raise HTTPException(422, "Listing must be an object")
    for key in CORRUPT_SPECIFIC_KEYS:
        value = listing.get(key)
        if value is not None and not isinstance(value, dict):
            raise HTTPException(422, f"{key} must be an object")


class ListingUpdate(BaseModel):
    listing: dict


class ListingResponse(BaseModel):
    conversation_id: str
    current_revision_id: str | None
    listing: dict
    revision_count: int
    can_send: bool
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []


class ValidationResponse(BaseModel):
    valid: bool
    errors: list[dict[str, str]]
    warnings: list[dict[str, str]]
    info: list[dict[str, str]]
    can_send: bool


@router.get("/api/conversations/{conv_id}/listing")
def get_listing(conv_id: str, db: Session = Depends(get_db)):
    conv_repo = ConversationRepo(db)
    if not conv_repo.get(conv_id):
        raise HTTPException(404, "Conversation not found")

    listing_repo = ListingRepo(db)
    revisions = listing_repo.get_revisions(conv_id)

    current = listing_repo.get_current(conv_id)
    revision_id = current.current_revision_id if current else None

    listing_data = {}
    if revisions:
        latest = revisions[0]
        listing_data = latest.listing_json

    photo_count = len(conv_repo.get_photos(conv_id))
    validation = validate_listing(listing_data, photo_count, require_photos=True)

    return ListingResponse(
        conversation_id=conv_id,
        current_revision_id=revision_id,
        listing=listing_data,
        revision_count=len(revisions),
        can_send=validation.can_send,
        errors=validation.errors,
        warnings=validation.warnings,
    )


@router.put("/api/conversations/{conv_id}/listing")
def update_listing(conv_id: str, body: ListingUpdate, db: Session = Depends(get_db)):
    conv_repo = ConversationRepo(db)
    if not conv_repo.get(conv_id):
        raise HTTPException(404, "Conversation not found")

    listing_repo = ListingRepo(db)
    current = listing_repo.get_current(conv_id)

    photo_count = len(conv_repo.get_photos(conv_id))
    _reject_corrupt_listing(body.listing)
    validation = validate_listing(body.listing, photo_count, require_photos=True)

    revision = listing_repo.save_revision(
        conv_id=conv_id,
        listing_json=body.listing,
        source="user_form",
        parent_revision_id=current.current_revision_id if current else None,
    )

    if current:
        current.validation_status = "valid" if validation.valid else "error"
        current.validation_errors = validation.errors + validation.warnings
        db.commit()

    return {
        "ok": True,
        "revision_id": revision.id,
        "validation": validation.model_dump(),
    }


@router.post("/api/conversations/{conv_id}/listing/validate")
def validate(conv_id: str, db: Session = Depends(get_db)):
    conv_repo = ConversationRepo(db)
    if not conv_repo.get(conv_id):
        raise HTTPException(404, "Conversation not found")

    listing_repo = ListingRepo(db)
    revisions = listing_repo.get_revisions(conv_id)
    listing_data = revisions[0].listing_json if revisions else {}

    photo_count = len(conv_repo.get_photos(conv_id))
    result = validate_listing(listing_data, photo_count, require_photos=True)

    return ValidationResponse(
        valid=result.valid,
        errors=result.errors,
        warnings=result.warnings,
        info=result.info,
        can_send=result.can_send,
    )


@router.get("/api/conversations/{conv_id}/revisions")
def get_revisions(conv_id: str, db: Session = Depends(get_db)):
    listing_repo = ListingRepo(db)
    revisions = listing_repo.get_revisions(conv_id)
    return [
        {
            "id": r.id,
            "source": r.source,
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "parent_revision_id": r.parent_revision_id,
            "title": r.listing_json.get("title", ""),
        }
        for r in revisions
    ]


@router.post("/api/conversations/{conv_id}/revisions/{revision_id}/restore")
def restore_revision(conv_id: str, revision_id: str, db: Session = Depends(get_db)):
    listing_repo = ListingRepo(db)
    target = listing_repo.get_revision(revision_id)
    if not target or target.conversation_id != conv_id:
        raise HTTPException(404, "Revision not found")

    current = listing_repo.get_current(conv_id)
    new_revision = listing_repo.save_revision(
        conv_id=conv_id,
        listing_json=target.listing_json,
        source="restore",
        parent_revision_id=current.current_revision_id if current else None,
    )
    return {"ok": True, "revision_id": new_revision.id}
