"""Resolve which leftover Vendoo fields to fill and with what values."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.orm import Session

from vendoo_studio.repositories.queries import FillLogRepo, ListingRepo
from vendoo_studio.services.fill_log import (
    FILLABLE_STATUSES,
    MAX_FILL_FIELDS,
    MAX_PATCH_VALUE,
    field_lookup_key,
    listing_value_for_field,
    normalize_field_label,
    preview_value,
)
from vendoo_studio.services.registry import SELLER_SETTING_LABELS


class FillFieldsError(ValueError):
    """The requested fields cannot be filled as asked."""


class FillFieldRequest(Protocol):
    id: str | None
    marketplace: str | None
    field: str | None
    value: str | None
    selector: str | None


@dataclass
class FillFieldsPlan:
    listing: dict
    revisions: list[Any]
    resolved: list[dict]
    patches: list[dict]


def plan_fill_fields(db: Session, job, requested_fields: Sequence[FillFieldRequest]) -> FillFieldsPlan:
    """Match requested fields to fill-log entries and pick a value for each one."""
    requested = list(requested_fields)[:MAX_FILL_FIELDS]
    if not requested:
        raise FillFieldsError("Add at least one field to fill")

    listing_repo = ListingRepo(db)
    revisions = listing_repo.get_revisions(job.conversation_id)
    listing = dict(revisions[0].listing_json) if revisions else dict(job.listing_snapshot or {})

    fill_repo = FillLogRepo(db)
    existing_ids = [str(item.id or "").strip() for item in requested if str(item.id or "").strip()]
    existing_by_id = {
        entry.id: entry
        for entry in fill_repo.get_for_job_ids(job.id, existing_ids)
    }

    resolved: list[dict] = []
    created_specs: list[dict] = []
    for item in requested:
        entry_id = str(item.id or "").strip()
        marketplace = str(item.marketplace or "").strip().lower()
        field = str(item.field or "").strip()
        selector = str(item.selector or "").strip()
        value = str(item.value or "").strip()
        entry = existing_by_id.get(entry_id) if entry_id else None
        if entry_id and entry is None:
            raise FillFieldsError("One or more leftover fields were not found on this job")
        if entry:
            if entry.status not in FILLABLE_STATUSES:
                raise FillFieldsError(f"{entry.field} is already filled")
            marketplace = marketplace or entry.marketplace
            field = field or entry.field
            selector = selector or (entry.selector or "")
        if not field:
            raise FillFieldsError("Each field needs a name")
        if not marketplace:
            marketplace = "general"
        if field_lookup_key(field) in SELLER_SETTING_LABELS:
            continue
        if not value:
            value = listing_value_for_field(listing, marketplace, field)
        if marketplace == "poshmark" and field_lookup_key(field) == "category":
            from vendoo_studio.services.registry import map_poshmark_category_path
            mapped = map_poshmark_category_path(listing.get("category_path") or value, listing)
            if mapped:
                value = mapped
        if marketplace == "mercari" and field_lookup_key(field) == "category":
            from vendoo_studio.services.registry import map_mercari_category_path
            mapped = map_mercari_category_path(listing.get("category_path") or value, listing)
            if mapped:
                value = mapped
        if not value:
            continue
        if len(value) > MAX_PATCH_VALUE:
            raise FillFieldsError(f"Value for {field} is too long ({len(value)} chars; max {MAX_PATCH_VALUE})")
        patch = {
            "marketplace": marketplace,
            "field": field,
            "selector": selector,
            "value": value,
        }
        if entry:
            patch["id"] = entry.id
            patch["entry"] = entry
        else:
            created_specs.append({
                "marketplace": marketplace,
                "field": field,
                "status": "new",
                "reason": "Waiting to fill missing field",
                "selector": selector,
                "value_preview": preview_value(value),
            })
        resolved.append(patch)

    if not resolved:
        raise FillFieldsError("No values to apply. Ask chat to write the missing values first.")

    if created_specs:
        created = fill_repo.add_entries(
            job_id=job.id,
            conversation_id=job.conversation_id,
            step="filling_fields",
            marketplace=created_specs[0]["marketplace"],
            entries=created_specs,
        )
        created_by_key = {
            (entry.marketplace, normalize_field_label(entry.field)): entry
            for entry in created
        }
        for patch in resolved:
            if patch.get("id"):
                continue
            entry = created_by_key.get((patch["marketplace"], normalize_field_label(patch["field"])))
            if entry:
                patch["id"] = entry.id
                patch["entry"] = entry

    patches = [{
        "id": patch.get("id") or "",
        "marketplace": patch["marketplace"],
        "field": patch["field"],
        "selector": patch.get("selector") or "",
        "value": patch["value"],
    } for patch in resolved]

    return FillFieldsPlan(listing=listing, revisions=revisions, resolved=resolved, patches=patches)
