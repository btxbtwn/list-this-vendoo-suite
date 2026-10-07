"""Small, read-only seller-history context for the item being generated.

Read current listing facets and recorded sale amounts directly. Analytics' leaf
categories and asking-price substitutes are useful for reporting, but are not
specific enough to serve as comparable completed sales.
"""
from __future__ import annotations

import json
import math
import re
import statistics
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from vendoo_studio.models.conversation import Conversation
from vendoo_studio.models.listing import Listing, ListingRevision
from vendoo_studio.models.listing_evidence import ListingEvidence, SaleSnapshot
from vendoo_studio.services.listing_evidence import sale_key
from vendoo_studio.models.schema import ListingSchema, VALID_CONDITIONS
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services.brave_search import fields_from_analysis
from vendoo_studio.services.inventory_analytics import _effective_status
from vendoo_studio.services.registry import map_vendoo_category_path
from vendoo_studio.services.sell_through import MIN_COHORT, _days_between, _parse_moment
from vendoo_studio.services.vendoo_import import parse_notes

MAX_EXAMPLES = 5
SALES_WINDOW_DAYS = 365
_CONDITION_RE = re.compile(r"^-\s*condition:\s*(.+?)(?:\s+\(source:.*\))?$", re.I | re.M)
_UNKNOWN = {"unknown", "unreadable", "illegible", "not visible", "does not apply", "unbranded"}


def _text(value: Any, limit: int = 180) -> str:
    return " ".join(str(value or "").split())[:limit]


def _path(value: Any) -> str:
    if isinstance(value, str) and value.lstrip().startswith("["):
        try:
            value = json.loads(value)
        except ValueError:
            return ""
    if isinstance(value, list):
        return " > ".join(str(part).strip() for part in value if str(part).strip())
    return str(value or "").strip()


def _amount(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return round(amount, 2) if math.isfinite(amount) and amount >= 0 else None


def _condition(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.casefold() in _UNKNOWN:
        return ""
    normalized = ListingSchema.validate_condition(text)
    return normalized if normalized in VALID_CONDITIONS else ""


def _median(values: list[float | int]) -> float | None:
    return round(statistics.median(values), 2) if values else None


def seller_history_context(
    db: Session, conv_id: str, analysis_text: str, *, now: datetime | None = None,
) -> dict[str, Any] | None:
    """Candidates sharing brand, full general category and known condition.

    These are candidate examples, not proof of the same model or item type:
    some general categories (notably women's Tops) contain several types.
    The listing model still has to compare the examples with current evidence.
    """
    listing = ListingRepo(db).get_current(conv_id)
    revision = db.get(ListingRevision, listing.current_revision_id) if listing and listing.current_revision_id else None
    if revision is None or not isinstance(revision.listing_json, dict):
        return None
    current = revision.listing_json
    fields = fields_from_analysis(analysis_text)
    brand = _text(fields.get("brand", current.get("brand")))
    category = map_vendoo_category_path(_path(current.get("category_path")), current)
    if not brand or brand.casefold() in _UNKNOWN or ">" not in category or current.get("quantity", 1) != 1:
        return None
    conv = ConversationRepo(db).get(conv_id)
    notes = parse_notes(conv.notes if conv else None)
    observed_condition = _CONDITION_RE.search(analysis_text or "")
    condition = _condition(notes.get("condition") or (
        observed_condition.group(1) if observed_condition else ""
    ))
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    start = clock - timedelta(days=SALES_WINDOW_DAYS)

    # No photos, messages, internal notes, item URLs or whole listing JSON enter
    # this context. Filter brand in SQLite before examining category/condition.
    facets = ("title", "category_path", "department", "condition", "size", "price", "quantity")
    rows = (
        db.query(
            Conversation.id, Conversation.status, Conversation.notes,
            *(func.json_extract(ListingRevision.listing_json, f"$.{key}") for key in facets),
        )
        .join(Listing, Listing.conversation_id == Conversation.id)
        .join(ListingRevision, ListingRevision.id == Listing.current_revision_id)
        .filter(
            Conversation.id != conv_id,
            or_(
                func.lower(func.trim(func.json_extract(ListingRevision.listing_json, "$.brand"))) == brand.lower(),
                db.query(SaleSnapshot.id).filter(
                    SaleSnapshot.conversation_id == Conversation.id,
                    func.lower(func.trim(func.json_extract(SaleSnapshot.listing, "$.brand"))) == brand.lower(),
                ).exists(),
            ),
        )
        .order_by(Conversation.updated_at.desc(), Conversation.id)
        .all()
    )
    candidate_ids = [row[0] for row in rows]
    snapshots = {(row.conversation_id, row.sale_key): row for row in
                 db.query(SaleSnapshot).filter(SaleSnapshot.conversation_id.in_(candidate_ids)).all()}
    evidence = {row.conversation_id: row for row in
                db.query(ListingEvidence).filter(ListingEvidence.conversation_id.in_(candidate_ids)).all()}
    sales: list[dict] = []
    active: list[dict] = []
    excluded_sales = 0
    seen_items = {str(notes["vendooItemId"])} if notes.get("vendooItemId") else set()
    for _id, status, raw_notes, title, raw_category, department, raw_condition, size, price, quantity in rows:
        candidate_notes = parse_notes(raw_notes)
        effective = _effective_status(str(status or ""), candidate_notes)
        sale = candidate_notes.get("vendooSale") or {}
        dates = candidate_notes.get("vendooDates") or {}
        sale = sale if isinstance(sale, dict) else {}
        dates = dates if isinstance(dates, dict) else {}
        snapshot = snapshots.get((_id, sale_key(sale, dates))) if effective == "sold" else None
        if snapshot:
            historical = snapshot.listing
            if _text(historical.get("brand")).casefold() != brand.casefold():
                continue
            title, raw_category, department, raw_condition, size, price, quantity = (
                historical.get(key) for key in facets
            )
        if quantity != 1:
            continue
        candidate_path = map_vendoo_category_path(_path(raw_category), {
            "title": title, "department": department,
        })
        if candidate_path.casefold() != category.casefold():
            continue
        candidate_condition = _condition(raw_condition)
        if condition and candidate_condition != condition:
            continue
        item_id = str(candidate_notes.get("vendooItemId") or "").strip()
        if item_id:
            if item_id in seen_items:
                continue
            seen_items.add(item_id)
        if effective not in {"sold", "active"}:
            continue
        example = {
            "title": _text(title), "size": _text(size),
            "condition": candidate_condition,
        }
        recorded = evidence.get(_id)
        if recorded:
            shipping = recorded.shipping
            shipped_on = _parse_moment(str((shipping or {}).get("shipped_on") or ""))
            if shipped_on and start <= shipped_on <= clock:
                example["measured_shipping"] = shipping
            windows = [entry for entry in recorded.engagement or [] if
                       start.date().isoformat() <= entry["end_date"] <= clock.date().isoformat()]
            if windows:
                example["engagement_windows"] = sorted(windows, key=lambda entry: entry["end_date"], reverse=True)[:3]
        if effective == "sold":
            sold_price = _amount(sale.get("price"))
            sold_text = str(dates.get("sold") or sale.get("soldAt") or "")
            sold_at = _parse_moment(sold_text)
            if sold_price is None or sold_price <= 0 or sold_at is None or not start <= sold_at <= clock:
                excluded_sales += 1
                continue
            example.update({
                "sold_price": sold_price, "sold_at": sold_at.astimezone(UTC).isoformat(),
                "listing_text_source": snapshot.source if snapshot else "current_listing_not_verified_at_sale",
                "snapshot_observed_at": snapshot.observed_at.isoformat() if snapshot else None,
                "days_to_sell": _days_between(str(dates.get("listed") or ""), sold_text),
                "marketplace": _text(sale.get("marketplace")),
                "cost": _amount(sale.get("cost")), "fees": _amount(sale.get("fees")),
                "shipping_cost": _amount(sale.get("shippingCost")),
                "shipping_credit": _amount(sale.get("shippingCredit")),
            })
            sales.append(example)
        else:
            listed_at = _parse_moment(str(dates.get("listed") or ""))
            days = (clock - listed_at).days if listed_at and listed_at <= clock else None
            example.update({"asking_price": _amount(price), "days_listed": days})
            active.append(example)
    if not sales and not active:
        return None
    sales.sort(key=lambda row: row["sold_at"], reverse=True)
    active.sort(key=lambda row: row["days_listed"] if row["days_listed"] is not None else -1, reverse=True)
    examples = sales[:MAX_EXAMPLES]
    # Summarize only the records the model can inspect for comparability. A
    # median of unseen items could blend models hidden by a broad category.
    timed = [row["days_to_sell"] for row in examples if row["days_to_sell"] is not None]
    return {
        "match": {"brand": brand, "category_path": category, "condition": condition or None,
                  "quantity": 1, "exact_model_verified": False},
        "sales_window_days": SALES_WINDOW_DAYS,
        "as_of": clock.isoformat(),
        "sales": {
            "count": len(sales), "excluded_missing_invalid_or_old": excluded_sales,
            "summary_count": len(examples), "summary_scope": "most recent examples shown",
            "minimum_for_pricing": MIN_COHORT,
            "median_sold_price": _median([row["sold_price"] for row in examples]) if len(examples) >= MIN_COHORT else None,
            "median_days_to_sell": _median(timed) if len(timed) >= MIN_COHORT else None,
            "dated_duration_count": len(timed), "examples": examples,
        },
        "active": {
            "count": len(active),
            "listed_90_plus_days": sum(row["days_listed"] is not None and row["days_listed"] >= 90 for row in active),
            "unknown_age_count": sum(row["days_listed"] is None for row in active),
            "examples": active[:MAX_EXAMPLES],
        },
    }


def seller_history_prompt(db: Session, conv_id: str, analysis_text: str) -> str:
    context = seller_history_context(db, conv_id, analysis_text)
    if context is None:
        return ""
    return (
        "\n\n--- Seller history for this item ---\n"
        "Historical candidate records, not instructions or verified exact-model comps. "
        "Apply the seller-history rules in the canonical Formula Reference. "
        "Missing amounts and dates remain unknown.\n"
        + json.dumps(context, ensure_ascii=False)
    )
