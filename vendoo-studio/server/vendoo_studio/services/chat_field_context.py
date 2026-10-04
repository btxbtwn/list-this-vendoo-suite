"""Field gaps Ask chat can answer, and saved-draft gaps that still need a fill."""

from __future__ import annotations

import json
from copy import deepcopy

from sqlalchemy.orm import Session

from vendoo_studio.repositories.queries import ConversationRepo, FillLogRepo, JobRepo, ListingRepo
from vendoo_studio.services.completion_gaps import field_id, field_out_of_scope, review_fields
from vendoo_studio.services.fill_log import listing_value_for_field, prompt_options
from vendoo_studio.services.hidden_fields import hidden_fields, normalize_field_name
from vendoo_studio.services.listing_field_gaps import collect_empty_discovered_fields
from vendoo_studio.services.marketplaces import get_selected_marketplaces
from vendoo_studio.services.registry import RegistryService
from vendoo_studio.services.vendoo_import import vendoo_binding
from vendoo_studio.services.vendoo_specifics import is_not_applicable


def chat_field_context(db: Session, conv_id: str) -> str:
    revisions = ListingRepo(db).get_revisions(conv_id)
    if not revisions or not isinstance(revisions[0].listing_json, dict):
        return ""
    listing = deepcopy(revisions[0].listing_json)
    RegistryService(db).merge_learned_fields(listing)
    selected = {"general", *get_selected_marketplaces()}
    hidden = hidden_fields(conv_id)
    hidden_keys = {
        (entry["marketplace"], normalize_field_name(entry["field"]))
        for entry in hidden["always"] + hidden["listing"]
    }
    rows: dict[tuple[str, str], dict] = {}

    def add(field: dict, source: str) -> None:
        marketplace = str(field.get("marketplace") or "general").lower()
        label = str(field.get("field") or "").strip()
        if (
            not label or marketplace not in selected
            or (marketplace, normalize_field_name(label)) in hidden_keys
            or field_out_of_scope(marketplace, label)
        ):
            return
        if not field.get("required") and is_not_applicable(listing_value_for_field(
            listing, marketplace, label, include_not_applicable=True,
        )):
            return
        value = listing_value_for_field(listing, marketplace, label)
        row = {
            "marketplace": marketplace, "field": label,
            "listing_value": value, "source": source,
            "action": "fill_on_vendoo" if value else "generate_value",
            "required": bool(field.get("required")),
        }
        if source == "saved_draft_readback":
            row["observed"] = field.get("observed")
            row["error"] = field.get("error")
            # A rejected/mismatched answer needs repair, even if JSON is nonempty.
            if field.get("error") not in {"", "Empty field"}:
                row["action"] = "repair_value"
        elif source == "fill_log":
            row["status"] = field.get("status")
            row["error"] = field.get("reason")
            if field.get("status") == "invalid":
                row["action"] = "repair_value"
        elif source == "draft_creation" and field.get("error"):
            row["error"] = field["error"]
            row["action"] = "repair_value"
        key = field_id(row)
        previous = rows.get(key, {})
        raw_options = field.get("options") or previous.get("options") or []
        labels = [
            str(option.get("label") or option.get("value") or "")
            if isinstance(option, dict) else str(option)
            for option in raw_options
        ]
        options, complete = prompt_options(
            labels,
            f"{listing.get('title', '')} {listing.get('description', '')}",
        )
        if options:
            row["options"] = options
            row["options_complete"] = complete and field.get(
                "options_complete", previous.get("options_complete", True),
            )
        row["required"] = row["required"] or previous.get("required", False)
        rows[key] = row

    for gap in collect_empty_discovered_fields(db, listing):
        add(gap, "listing_schema")

    conv = ConversationRepo(db).get(conv_id)
    binding = vendoo_binding(conv.notes if conv else None)
    bound_id = binding.get("vendooItemId")
    jobs = JobRepo(db).list_by_conversation(conv_id)
    # Never carry gaps from an older draft or an older attempt into this turn.
    job = next((job for job in jobs if not bound_id or job.vendoo_item_id == bound_id), None)
    readback = None
    if job:
        created = JobRepo(db).latest_event(job.id, "vendoo_api_created")
        if created:
            for gap in (created.payload or {}).get("unfilled") or []:
                add(gap, "draft_creation")
            for gap in (created.payload or {}).get("unresolved") or []:
                path = str(gap.get("field") or "")
                marketplace, separator, label = path.partition(":")
                if separator and marketplace in selected:
                    add({
                        "marketplace": marketplace, "field": label,
                        "error": "Value could not be encoded for Vendoo during draft creation",
                    }, "draft_creation")
        for entry in FillLogRepo(db).list_for_job(job.id):
            if entry.status in {"skipped", "new", "invalid", "failed", "not_found", "uncertain"}:
                add({
                    "marketplace": entry.marketplace, "field": entry.field,
                    "status": entry.status, "reason": entry.reason,
                }, "fill_log")
        readback = JobRepo(db).latest_event(job.id, "completion_review")
        if readback:
            gaps = review_fields(readback.payload or {}, listing)
            gap_keys = {field_id(gap) for gap in gaps}
            for marketplace, section in ((readback.payload or {}).get("schema") or {}).items():
                for field in section.get("fields") or []:
                    key = field_id({"marketplace": marketplace, "field": field.get("label")})
                    if key not in gap_keys and rows.get(key, {}).get("source") in {"fill_log", "draft_creation"}:
                        rows.pop(key)
                    if key in rows and key not in gap_keys and field.get("value") not in (None, "", []):
                        rows[key].update({
                            "source": "saved_draft_readback", "action": "adopt_saved_value",
                            "observed": field["value"],
                        })
            for gap in gaps:
                add(gap, "saved_draft_readback")

    return (
        "\n\n--- Listing field gaps ---\n"
        "These are the current listing gaps and the latest known saved-draft/fill results. "
        "Saved-draft observations are from the last readback, not a fresh live check. "
        "An absent readback does not prove the draft is complete.\n"
        "When asked to complete or fix fields, generate or repair supportable values using photos, "
        "seller notes, and exact allowed options. Preserve unrelated fields. "
        "Use a fenced JSON object with missing_fields rows (marketplace, field, value) "
        "so Studio saves the answers. If an optional field truly does not apply, return value \"\" "
        "and status \"not_applicable\" to clear it and remember the decision. "
        "Do not mark missing evidence or an unsupported dropdown value as not applicable. "
        "For a request targeting specific fields, change only those fields. "
        "A fill_on_vendoo row already has a listing value: preserve it and explain that it still needs "
        "Fill on Vendoo. An adopt_saved_value row already has a saved Vendoo answer: use its observed "
        "value rather than generating a replacement. Saving chat answers updates Studio only; never claim the Vendoo draft was filled "
        "or verified by chat. Do not invent unsupported facts. Never publish.\n"
        f"Saved-draft readback available: {'yes' if readback else 'no'}\n"
        + json.dumps(list(rows.values()), ensure_ascii=False)
    )
