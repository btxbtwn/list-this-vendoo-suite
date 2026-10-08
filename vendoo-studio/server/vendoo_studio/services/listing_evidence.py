"""Capture evidence with provenance; never infer measurements or preferences."""
from __future__ import annotations

import copy
import json
from datetime import UTC

from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert

from vendoo_studio.models.listing_evidence import ListingCorrection, SaleSnapshot
from vendoo_studio.services.sell_through import _parse_moment


def sale_key(sale: dict, dates: dict) -> str:
    sold_at = _parse_moment(str(dates.get("sold") or sale.get("soldAt") or ""))
    if not sold_at:
        return ""
    return f"{str(sale.get('marketplace') or '').lower()}:{sold_at.astimezone(UTC).isoformat()}"


def capture_sale_snapshot(db: Session, conv_id: str, item: dict | None, form: dict | None = None) -> None:
    """Freeze the remote listing at the first observation of each dated sale.

    Observation can happen after the actual sale. Never call it verified
    at-sale text, or substitute a local unsent draft for the remote listing.
    """
    from vendoo_studio.services.vendoo_import import (
        listing_from_vendoo, vendoo_dates, vendoo_item_sold, vendoo_sale,
    )

    if not vendoo_item_sold(item, form):
        return
    key = sale_key(vendoo_sale(item, form), vendoo_dates(item, form))
    if not key or db.query(SaleSnapshot.id).filter_by(conversation_id=conv_id, sale_key=key).first():
        return
    db.execute(insert(SaleSnapshot).values(
        conversation_id=conv_id, sale_key=key,
        listing=copy.deepcopy(listing_from_vendoo(item, form)),
        source="vendoo_first_observed_sold",
    ).on_conflict_do_nothing(index_elements=["conversation_id", "sale_key"]))


def explicit_changes(previous: dict, submitted: dict) -> dict:
    """Diff raw seller input BEFORE size/title/dropdown normalization.

    Whole JSON submissions are deliberate edits too. No history is fabricated
    from old user_form revisions or from automated revisions.
    """
    from vendoo_studio.models.schema import ListingSchema
    changes = {}
    allowed = set(ListingSchema.model_fields) - {"sku", "internal_notes", "labels", "photos", "photo_urls", "cost"}

    def walk(before, after, path):
        if isinstance(before, dict) and isinstance(after, dict):
            for key in sorted(set(before) | set(after)):
                walk(before.get(key), after.get(key), [*path, key])
        elif before != after:
            # Private inventory fields and economics never become model examples.
            if not path or path[0] not in allowed:
                return
            changes[".".join(path)] = {"before": copy.deepcopy(before), "after": copy.deepcopy(after)}

    walk(previous, submitted, [])
    return changes


def record_correction(db: Session, conv_id: str, revision_id: str, listing: dict, changes: dict) -> None:
    if changes:
        db.add(ListingCorrection(conversation_id=conv_id, revision_id=revision_id,
                                 category_path=str(listing.get("category_path") or ""),
                                 brand=str(listing.get("brand") or ""), changes=changes))


def corrections_context(db: Session, conv_id: str, listing: dict) -> dict:
    own = db.query(ListingCorrection).filter_by(conversation_id=conv_id).order_by(ListingCorrection.created_at.desc()).limit(30).all()
    corrections = {}
    for row in own:
        for field, change in row.changes.items():
            if field not in corrections and len(corrections) < 20:
                corrections[field] = {"value": change["after"], "source": row.source, "recorded_at": row.created_at.isoformat()}
    # Examples from other items teach editing choices, not facts about this one.
    examples = []
    related = db.query(ListingCorrection).filter(
        ListingCorrection.conversation_id != conv_id,
        ListingCorrection.source == "user_form",
        ListingCorrection.category_path == str(listing.get("category_path") or ""),
        ListingCorrection.brand == str(listing.get("brand") or ""),
    ).order_by(ListingCorrection.created_at.desc()).limit(50).all()
    seen = set()
    for row in related:
        if row.conversation_id in seen:
            continue
        changed_copy = {key: {side: str(value or "")[:600] for side, value in change.items()}
                        for key, change in row.changes.items() if key in {"title", "description"}}
        if changed_copy:
            seen.add(row.conversation_id)
            examples.append({"changes": changed_copy, "recorded_at": row.created_at.isoformat()})
        if len(examples) == 5:
            break
    return {"current_item_corrections": corrections, "related_copy_edits": examples}


def generation_evidence_prompt(db: Session, conv_id: str) -> str:
    from vendoo_studio.repositories.queries import ListingRepo
    repo = ListingRepo(db)
    current = repo.get_current(conv_id)
    revision = repo.get_revision(current.current_revision_id) if current and current.current_revision_id else None
    listing = revision.listing_json if revision else {}
    context = corrections_context(db, conv_id, listing)
    if not any(context.values()):
        return ""
    # Cap individual seller values too; no private notes or whole revisions.
    for value in context["current_item_corrections"].values():
        if len(json.dumps(value["value"], ensure_ascii=False)) > 600:
            value["value"] = str(value["value"])[:600]
    return "\n\n--- Seller corrections ---\n" + json.dumps(context, ensure_ascii=False)
