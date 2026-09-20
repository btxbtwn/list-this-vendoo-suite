"""Rank inventory rows into a short Suggestions feed.

Rules only: no model call, no publish. Each conversation contributes at most
one card, the highest-priority kind it matches. The seller opens the listing
and uses the existing Generate / editor / price-drop controls.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from vendoo_studio.models.conversation import Photo
from vendoo_studio.models.listing import Listing
from vendoo_studio.repositories.queries import BUSY_LISTING_STATUSES, ConversationRepo
from vendoo_studio.services.vendoo_import import parse_notes

MAX_SUGGESTIONS = 20
STALE_MIN_DAYS = 30
COVER_THUMB_SIZE = 96

KIND_FAILED = "failed"
KIND_READY_TO_GENERATE = "ready_to_generate"
KIND_FIX_VALIDATION = "fix_validation"
KIND_STALE_ACTIVE = "stale_active"
KIND_READY_TO_REVIEW = "ready_to_review"

KIND_BASE_SCORE = {
    KIND_FAILED: 500,
    KIND_READY_TO_GENERATE: 400,
    KIND_FIX_VALIDATION: 300,
    KIND_STALE_ACTIVE: 200,
    KIND_READY_TO_REVIEW: 100,
}

MARKETPLACE_LABELS = {
    "ebay": "eBay",
    "etsy": "Etsy",
    "poshmark": "Poshmark",
    "mercari": "Mercari",
    "depop": "Depop",
    "facebook": "Facebook",
    "shopify": "Shopify",
    "vinted": "Vinted",
    "whatnot": "Whatnot",
    "grailed": "Grailed",
    "vestiaire": "Vestiaire Collective",
    "vestiaireApi": "Vestiaire Collective",
    "sellwild": "Sellwild",
}


def list_suggestions(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = MAX_SUGGESTIONS,
) -> list[dict[str, Any]]:
    """Return ranked suggestion cards for the empty workspace and sidebar."""
    when = now or datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)

    repo = ConversationRepo(db)
    repo.reconcile_job_statuses()
    covers = repo.cover_photo_ids()
    photo_counts = _photo_counts(db)
    listings = _listing_state(db)

    cards: list[dict[str, Any]] = []
    for conv in repo.list_all():
        if conv.settled_at is not None:
            continue
        status = str(conv.status or "draft")
        if status == "sold" or status in BUSY_LISTING_STATUSES:
            continue
        card = _card_for(
            conv,
            status=status,
            photo_count=photo_counts.get(conv.id, 0),
            listing=listings.get(conv.id),
            cover_photo_id=covers.get(conv.id),
            now=when,
        )
        if card:
            cards.append(card)

    cards.sort(key=lambda card: (-int(card["score"]), str(card["conversation_id"])))
    return cards[: max(0, int(limit))]


def _photo_counts(db: Session) -> dict[str, int]:
    rows = (
        db.query(Photo.conversation_id, func.count(Photo.id))
        .group_by(Photo.conversation_id)
        .all()
    )
    return {conv_id: int(count) for conv_id, count in rows}


def _listing_state(db: Session) -> dict[str, dict[str, Any]]:
    rows = db.query(
        Listing.conversation_id,
        Listing.current_revision_id,
        Listing.validation_status,
    ).all()
    return {
        conv_id: {
            "revision_id": revision_id,
            "validation_status": validation_status,
        }
        for conv_id, revision_id, validation_status in rows
    }


def _card_for(
    conv,
    *,
    status: str,
    photo_count: int,
    listing: dict[str, Any] | None,
    cover_photo_id: str | None,
    now: datetime,
) -> dict[str, Any] | None:
    notes = parse_notes(conv.notes)
    marketplaces = _marketplaces(notes)
    has_revision = bool(listing and listing.get("revision_id"))
    kind: str | None = None
    reason = ""
    score = 0

    if status == KIND_FAILED:
        kind = KIND_FAILED
        reason = "The last send to Vendoo failed"
        score = KIND_BASE_SCORE[KIND_FAILED]
    elif status == "draft" and photo_count > 0 and not has_revision:
        kind = KIND_READY_TO_GENERATE
        reason = "Photos are ready to generate a listing"
        score = KIND_BASE_SCORE[KIND_READY_TO_GENERATE]
    elif has_revision and str(listing.get("validation_status") or "") == "error":
        kind = KIND_FIX_VALIDATION
        reason = "Listing fields need to be fixed before sending"
        score = KIND_BASE_SCORE[KIND_FIX_VALIDATION]
    elif status == "active":
        days = _listed_days_ago(notes, now)
        if days is not None and days >= STALE_MIN_DAYS:
            kind = KIND_STALE_ACTIVE
            reason = _stale_reason(days, marketplaces)
            score = KIND_BASE_SCORE[KIND_STALE_ACTIVE] + min(days, 365)
    elif status == "draft" and has_revision and not marketplaces:
        kind = KIND_READY_TO_REVIEW
        reason = "Draft is ready to review and send"
        score = KIND_BASE_SCORE[KIND_READY_TO_REVIEW]

    if not kind:
        return None

    cover = (
        f"/api/photos/{cover_photo_id}/thumb?size={COVER_THUMB_SIZE}"
        if cover_photo_id
        else (str(notes.get("vendooCoverUrl") or "") or None)
    )
    return {
        "conversation_id": conv.id,
        "kind": kind,
        "title": (conv.title or "").strip() or "Untitled",
        "reason": reason,
        "action": "open",
        "score": score,
        "cover_photo_url": cover,
    }


def _marketplaces(notes: dict[str, Any]) -> list[str]:
    raw = notes.get("vendooMarketplaces")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]


def _listed_days_ago(notes: dict[str, Any], now: datetime) -> int | None:
    dates = notes.get("vendooDates") if isinstance(notes.get("vendooDates"), dict) else {}
    text = str(dates.get("listed") or "").strip()
    if not text:
        return None
    try:
        listed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if listed.tzinfo is None:
        listed = listed.replace(tzinfo=UTC)
    days = int((now - listed).total_seconds() // timedelta(days=1).total_seconds())
    return days if days >= 0 else None


def _stale_reason(days: int, marketplaces: list[str]) -> str:
    age = f"Listed {days} day{'s' if days != 1 else ''} ago"
    labels = [_marketplace_label(item) for item in marketplaces]
    if not labels:
        return age
    if len(labels) == 1:
        return f"{age} on {labels[0]}"
    return f"{age} on {', '.join(labels[:-1])} and {labels[-1]}"


def _marketplace_label(marketplace_id: str) -> str:
    if marketplace_id in MARKETPLACE_LABELS:
        return MARKETPLACE_LABELS[marketplace_id]
    return marketplace_id[:1].upper() + marketplace_id[1:] if marketplace_id else marketplace_id
