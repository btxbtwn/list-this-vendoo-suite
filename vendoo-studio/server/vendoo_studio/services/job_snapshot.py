"""Listing snapshots, retry resume points, and blocker summaries for automation jobs."""

from __future__ import annotations

from sqlalchemy.orm import Session

from vendoo_studio.models.mercari_shipping import DEFAULT_SHIPPING_LABEL
from vendoo_studio.repositories.queries import JobRepo


def generate_sku(listing: dict) -> str:
    brand = str(listing.get("brand") or "").strip()
    size = str(listing.get("size") or "").strip()

    def slug(text: str) -> str:
        chars = [ch.upper() if ch.isalnum() else "-" for ch in text]
        return "-".join(part for part in "".join(chars).split("-") if part)

    parts = []
    if brand:
        parts.append(slug(brand))
    if size:
        parts.append(slug(size))
    return "-".join(parts) if parts else "ITEM"


_NON_RESUMABLE_STEPS = frozenset({
    "",
    "queued",
    "accepted",
    "awaiting_extension",
    "filling_fields",
    "imported",
    "completed",
    "cancelled",
})


def resume_step_for_retry(job) -> str | None:
    """Return the pipeline step a failed job should resume from, if any."""
    if getattr(job, "status", None) != "failed":
        return None
    step = str(getattr(job, "current_step", None) or "").strip()
    if step in _NON_RESUMABLE_STEPS:
        return None

    has_draft = bool(getattr(job, "vendoo_item_id", None) or getattr(job, "vendoo_url", None))
    general_steps = {
        "opening_vendoo",
        "waiting_ready",
        "uploading_photos",
        "clearing_general",
        "filling_general",
        "saving_general",
        "auditing_general",
    }
    if step in general_steps:
        return step

    marketplace_prefixes = ("clearing_", "filling_", "saving_", "auditing_")
    if step.startswith("auditing_"):
        marketplace = step[len("auditing_") :]
        if marketplace and marketplace != "general":
            return step if has_draft else None
    if step == "discovering_schema" or step.startswith(marketplace_prefixes):
        return step if has_draft else None

    return None


def validation_error_detail(validation) -> str:
    messages = [err.get("message", "") for err in validation.errors if err.get("message")]
    return "; ".join(messages) or "Listing cannot be sent to Vendoo. Fix validation errors first."


def prepare_listing_snapshot(
    db: Session,
    conv,
    listing_json: dict,
    *,
    prefer_listing_category: bool = False,
) -> dict:
    from vendoo_studio.services.marketplaces import selected_fillable_platforms
    from vendoo_studio.services.registry import RegistryService, align_listing_gender
    from vendoo_studio.services.vendoo_import import parse_notes, split_vendoo_labels

    listing_snapshot = dict(listing_json or {})
    conv_notes = parse_notes(getattr(conv, "notes", None))
    labels = split_vendoo_labels(conv_notes.get("vendooLabels"))
    if labels:
        listing_snapshot["labels"] = labels
    # Item Details COG and Notes are Vendoo's Cost of Goods and Internal Notes.
    cog_raw = str(conv_notes.get("cog") or "").strip()
    try:
        cog = float(cog_raw) if cog_raw else None
    except ValueError:
        cog = None
    if cog is not None:
        listing_snapshot["cost"] = cog
    seller_notes = str(conv_notes.get("sellerNotes") or "").strip()
    if seller_notes:
        listing_snapshot["internal_notes"] = seller_notes
    listing_category = str(listing_snapshot.get("category_path") or "").strip()
    category_override = str(conv_notes.get("categoryOverride") or "").strip()
    if category_override and (not prefer_listing_category or not listing_category):
        listing_snapshot["category_path"] = category_override
    price_raw = str(conv_notes.get("poshmarkOriginalPrice") or "").strip()
    try:
        poshmark_price = float(price_raw) if price_raw else 0
    except ValueError:
        poshmark_price = 0
    poshmark = listing_snapshot.get("poshmark_specifics") or {}
    if not isinstance(poshmark, dict):
        poshmark = {}
    poshmark["originalPrice"] = poshmark_price
    listing_snapshot["poshmark_specifics"] = poshmark
    align_listing_gender(listing_snapshot)
    ensure_listing_defaults(listing_snapshot)
    registry = RegistryService(db)
    registry.merge_learned_fields(listing_snapshot)
    for marketplace in selected_fillable_platforms():
        registry.validate_dropdown_fields(
            listing_snapshot, marketplace, listing_snapshot.get("category_path"),
        )
    return listing_snapshot


def ensure_listing_defaults(listing_snapshot: dict) -> None:
    if not isinstance(listing_snapshot, dict):
        return

    from vendoo_studio.models.schema import ListingSchema

    condition = listing_snapshot.get("condition")
    if condition:
        listing_snapshot["condition"] = ListingSchema.validate_condition(condition)

    if not str(listing_snapshot.get("sku") or "").strip():
        listing_snapshot["sku"] = generate_sku(listing_snapshot)

    from vendoo_studio.services.registry import map_vendoo_category_path

    mapped_category = map_vendoo_category_path(
        str(listing_snapshot.get("category_path") or ""),
        listing_snapshot,
    )
    if mapped_category:
        listing_snapshot["category_path"] = mapped_category

    mercari = listing_snapshot.get("mercari_specifics") or {}
    if not isinstance(mercari, dict):
        mercari = {}
    label = str(mercari.get("shippingLabel") or "").strip()
    mercari["shippingLabel"] = label or DEFAULT_SHIPPING_LABEL
    listing_snapshot["mercari_specifics"] = mercari

    from vendoo_studio.models.validation import normalize_listing_dropdowns
    normalize_listing_dropdowns(listing_snapshot)


def blocker_fields_for_job(job) -> list[dict] | None:
    """Compact marketplace/field targets from the latest completion pause event."""
    step = str(getattr(job, "current_step", None) or "").strip()
    if step not in {"completion_blocked", "awaiting_answers"}:
        return None
    if not str(getattr(job, "last_error", None) or "").strip():
        return None
    from sqlalchemy.orm import object_session

    session = object_session(job)
    if session is None:
        return None
    event = JobRepo(session).latest_event(job.id, step)
    raw = (event.payload or {}).get("fields") if event and isinstance(event.payload, dict) else None
    if not isinstance(raw, list) or not raw:
        return None
    compact: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        marketplace = str(item.get("marketplace") or "").strip().lower()
        field = str(item.get("field") or "").strip()
        if not marketplace or not field:
            continue
        key = f"{marketplace}:{field.casefold()}"
        if key in seen:
            continue
        seen.add(key)
        row: dict = {"marketplace": marketplace, "field": field}
        expected = item.get("expected")
        observed = item.get("observed")
        error = item.get("error")
        if expected not in (None, ""):
            row["expected"] = expected
        if observed not in (None, ""):
            row["observed"] = observed
        if error not in (None, ""):
            row["error"] = error
        options = item.get("options")
        if isinstance(options, list) and options:
            labels: list[str] = []
            for option in options:
                if isinstance(option, dict):
                    label = str(option.get("label") or option.get("value") or "").strip()
                else:
                    label = str(option).strip()
                if label and label not in labels:
                    labels.append(label)
                if len(labels) >= 20:
                    break
            if labels:
                row["options"] = labels
        compact.append(row)
        if len(compact) >= 40:
            break
    return compact or None
