from __future__ import annotations

import copy
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.models.validation import normalize_listing_dropdowns, validate_listing
from vendoo_studio.repositories.queries import ListingRepo, ConversationRepo
from vendoo_studio.services.price_drop import (
    PRICE_DROP_SOURCE,
    apply_price_to_listing,
    build_preview,
    listing_price,
    whole_dollars,
)

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
        listing_data = copy.deepcopy(latest.listing_json)

    if isinstance(listing_data, dict) and normalize_listing_dropdowns(listing_data):
        revision = listing_repo.save_revision(
            conv_id,
            listing_data,
            source="dropdown_normalize",
            parent_revision_id=revision_id,
        )
        revision_id = revision.id
        revisions = listing_repo.get_revisions(conv_id)

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
    from vendoo_studio.models.job import ACTIVE_JOB_STATUSES
    from vendoo_studio.repositories.queries import JobRepo
    from vendoo_studio.services.listing_generate import (
        propagate_general_size,
        sanitize_listing_sizes,
    )
    from vendoo_studio.services.schema_probe import is_schema_probe_job

    conv_repo = ConversationRepo(db)
    if not conv_repo.get(conv_id):
        raise HTTPException(404, "Conversation not found")

    listing_repo = ListingRepo(db)
    current = listing_repo.get_current(conv_id)

    photo_count = len(conv_repo.get_photos(conv_id))
    _reject_corrupt_listing(body.listing)
    sanitize_listing_sizes(body.listing)
    propagate_general_size(body.listing)
    normalize_listing_dropdowns(body.listing)
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

    # Keep in-flight / paused automation on the edited Studio form payload.
    refresh_statuses = set(ACTIVE_JOB_STATUSES) | {"failed"}
    for job in JobRepo(db).list_by_conversation(conv_id):
        if job.status not in refresh_statuses or is_schema_probe_job(job):
            continue
        platforms = (job.listing_snapshot or {}).get("platforms") if isinstance(job.listing_snapshot, dict) else None
        snapshot = dict(body.listing)
        if isinstance(platforms, list):
            snapshot["platforms"] = platforms
        job.listing_snapshot = snapshot

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
    listing_data = copy.deepcopy(revisions[0].listing_json) if revisions else {}
    normalize_listing_dropdowns(listing_data)

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


class PriceDropApply(BaseModel):
    price: float = Field(..., gt=0)
    percent: float | None = None
    mode: Literal["percent", "comps", "custom"] = "custom"


def _current_listing(conv_id: str, db: Session) -> tuple[dict, list]:
    conv_repo = ConversationRepo(db)
    if not conv_repo.get(conv_id):
        raise HTTPException(404, "Conversation not found")
    listing_repo = ListingRepo(db)
    revisions = listing_repo.get_revisions(conv_id)
    if not revisions or not isinstance(revisions[0].listing_json, dict):
        raise HTTPException(400, "Listing has no price to drop")
    listing = copy.deepcopy(revisions[0].listing_json)
    if listing_price(listing) is None:
        raise HTTPException(400, "Listing has no price to drop")
    return listing, revisions


@router.post("/api/conversations/{conv_id}/price-drop/preview")
async def preview_price_drop(conv_id: str, db: Session = Depends(get_db)):
    """Live comps + history-aware suggestion. Does not change the listing."""
    from vendoo_studio.services.listing_generate import latest_photo_analysis

    from vendoo_studio.services.sell_through import collect_outcomes, listing_age_days

    listing, revisions = _current_listing(conv_id, db)
    conv_repo = ConversationRepo(db)
    analysis = latest_photo_analysis(conv_repo.get_messages(conv_id))
    conv = conv_repo.get(conv_id)
    try:
        return await build_preview(
            listing,
            revisions,
            analysis_text=analysis,
            sold_outcomes=collect_outcomes(db),
            age_days=listing_age_days(conv.notes if conv else None),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/conversations/{conv_id}/price-drop")
def apply_price_drop(conv_id: str, body: PriceDropApply, db: Session = Depends(get_db)):
    """Apply a confirmed whole-dollar price; records a ``price_drop`` revision."""
    from vendoo_studio.models.job import ACTIVE_JOB_STATUSES
    from vendoo_studio.repositories.queries import JobRepo
    from vendoo_studio.services.listing_generate import (
        propagate_general_size,
        sanitize_listing_sizes,
    )
    from vendoo_studio.services.schema_probe import is_schema_probe_job

    listing, _revisions = _current_listing(conv_id, db)
    current = listing_price(listing)
    target = whole_dollars(body.price)
    if current is not None and target >= current:
        raise HTTPException(400, "New price must be lower than the current price")

    listing_repo = ListingRepo(db)
    current_row = listing_repo.get_current(conv_id)
    updated = apply_price_to_listing(listing, target)
    sanitize_listing_sizes(updated)
    propagate_general_size(updated)
    normalize_listing_dropdowns(updated)

    photo_count = len(ConversationRepo(db).get_photos(conv_id))
    validation = validate_listing(updated, photo_count, require_photos=True)
    revision = listing_repo.save_revision(
        conv_id=conv_id,
        listing_json=updated,
        source=PRICE_DROP_SOURCE,
        parent_revision_id=current_row.current_revision_id if current_row else None,
    )
    if current_row:
        current_row.validation_status = "valid" if validation.valid else "error"
        current_row.validation_errors = validation.errors + validation.warnings

    refresh_statuses = set(ACTIVE_JOB_STATUSES) | {"failed"}
    for job in JobRepo(db).list_by_conversation(conv_id):
        if job.status not in refresh_statuses or is_schema_probe_job(job):
            continue
        platforms = (job.listing_snapshot or {}).get("platforms") if isinstance(job.listing_snapshot, dict) else None
        snapshot = dict(updated)
        if isinstance(platforms, list):
            snapshot["platforms"] = platforms
        job.listing_snapshot = snapshot

    db.commit()
    return {
        "ok": True,
        "revision_id": revision.id,
        "price": target,
        "previous_price": current,
        "percent": body.percent,
        "mode": body.mode,
        "validation": validation.model_dump(),
    }
