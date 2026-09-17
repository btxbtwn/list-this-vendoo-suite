"""Save listing changes that come back from the chat assistant."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services.listing_generate import (
    extract_listing_json,
    listing_save_summary,
    looks_like_listing_attempt,
    repair_listing_json,
)
from vendoo_studio.services.listing_patch import apply_json_patch, extract_json_patch
from vendoo_studio.services.registry import align_listing_gender


def _sync_category_override(db: Session, conv_id: str, listing: dict) -> None:
    from vendoo_studio.services.vendoo_import import merge_notes, parse_notes

    category = str((listing or {}).get("category_path") or "").strip()
    if not category:
        return
    conv = ConversationRepo(db).get(conv_id)
    if not conv:
        return
    current = str(parse_notes(conv.notes).get("categoryOverride") or "").strip()
    if not current or current == category:
        return
    conv.notes = merge_notes(conv.notes, {"categoryOverride": category})
    db.commit()


def save_listing_revision(db: Session, conv_id: str, listing: dict, *, operations: list[dict] | None = None) -> dict:
    updated = align_listing_gender(listing, operations)
    stamped = _stamp_learned_fields(db, updated)
    revisions = ListingRepo(db).get_revisions(conv_id)
    parent_id = revisions[0].id if revisions else None
    ListingRepo(db).save_revision(
        conv_id,
        stamped,
        source="model_refinement",
        parent_revision_id=parent_id,
    )
    _sync_category_override(db, conv_id, stamped)
    return stamped


def _stamp_learned_fields(db: Session, listing: dict) -> dict:
    from vendoo_studio.services.registry import RegistryService

    if isinstance(listing, dict):
        RegistryService(db).merge_learned_fields(listing)
    return listing


def _patch_changes_category(operations: list[dict] | None) -> bool:
    for op in operations or []:
        if not isinstance(op, dict):
            continue
        path = str(op.get("path") or "").replace("~1", "/").rstrip("/").lower()
        if path.endswith("category_path") or path.endswith("categorypath"):
            return True
    return False


def _requested_category_path(operations: list[dict] | None) -> str:
    requested = ""
    for op in operations or []:
        if not isinstance(op, dict) or op.get("op") not in {"replace", "add"}:
            continue
        path = str(op.get("path") or "").replace("~1", "/").rstrip("/").lower()
        if path.endswith("category_path") or path.endswith("categorypath"):
            requested = str(op.get("value") or "").strip()
    return requested


async def _maybe_resolve_vendoo_category(
    db: Session,
    conv_id: str,
    *,
    operations: list[dict] | None = None,
) -> None:
    if not _patch_changes_category(operations):
        return
    from vendoo_studio.services.category_lookup import resolve_listing_category

    result = await resolve_listing_category(
        db,
        conv_id,
        query=_requested_category_path(operations),
    )
    repo = ConversationRepo(db)
    if result.get("skipped"):
        return
    if result.get("ok") and result.get("path"):
        repo.add_message(
            conv_id,
            "system",
            f"Matched Vendoo category: {result['path']}",
            provider="system",
            model="",
        )
        return
    if result.get("error"):
        repo.add_message(
            conv_id,
            "system",
            f"Could not match a Vendoo category yet: {result['error']}",
            provider="system",
            model="",
        )


def _save_missing_fields(db: Session, conv_id: str, missing_fields: list[dict]) -> bool:
    from vendoo_studio.services.fill_log import (
        FillLogService,
        summarize_missing_fields,
        write_values_into_listing,
    )

    revisions = ListingRepo(db).get_revisions(conv_id)
    if not revisions:
        ConversationRepo(db).add_message(
            conv_id,
            "system",
            "Could not save field values — generate a listing first, then Ask chat again.",
            provider="system",
            model="",
        )
        return False
    updated = write_values_into_listing(dict(revisions[0].listing_json), missing_fields)
    save_listing_revision(db, conv_id, updated)
    FillLogService(db).record_generated_values(conv_id, missing_fields)
    ConversationRepo(db).add_message(
        conv_id,
        "system",
        summarize_missing_fields(missing_fields),
        provider="system",
        model="",
    )
    return True


def apply_listing_payload(db: Session, conv_id: str, full_text: str) -> tuple[list[dict] | None, bool]:
    from vendoo_studio.services.fill_log import extract_missing_fields

    missing_fields = extract_missing_fields(full_text)
    if missing_fields:
        return None, _save_missing_fields(db, conv_id, missing_fields)

    parsed_ops = extract_json_patch(full_text)
    if parsed_ops:
        lr = ListingRepo(db)
        revisions = lr.get_revisions(conv_id)
        if not revisions:
            return None, False
        updated = apply_json_patch(dict(revisions[0].listing_json), parsed_ops)
        save_listing_revision(db, conv_id, updated, operations=parsed_ops)
        ConversationRepo(db).add_message(
            conv_id,
            "system",
            "Saved those changes to the listing.",
            provider="system",
            model="",
        )
        return parsed_ops, True

    parsed = extract_listing_json(full_text)
    if parsed:
        saved = save_listing_revision(db, conv_id, parsed)
        ConversationRepo(db).add_message(
            conv_id,
            "system",
            listing_save_summary(db, conv_id, saved),
            provider="system",
            model="",
        )
        return None, True
    return None, False


async def apply_listing_payload_with_repair(
    db: Session,
    conv_id: str,
    full_text: str,
    provider,
    *,
    user_message: str = "",
) -> tuple[list[dict] | None, bool]:
    from vendoo_studio.services.fill_log import (
        is_missing_fields_request,
        looks_like_missing_fields_attempt,
        repair_missing_fields,
    )

    operations, saved = apply_listing_payload(db, conv_id, full_text)
    if saved:
        return operations, True

    ask_fields = is_missing_fields_request(user_message)
    if ask_fields or looks_like_missing_fields_attempt(full_text):
        repaired_fields = await repair_missing_fields(provider, full_text, user_message)
        if repaired_fields and _save_missing_fields(db, conv_id, repaired_fields):
            return None, True
        if ask_fields:
            ConversationRepo(db).add_message(
                conv_id,
                "system",
                "Could not save field values into the listing JSON. Retry Ask chat.",
                provider="system",
                model="",
            )
        return None, False

    if extract_listing_json(full_text):
        return None, False
    if extract_json_patch(full_text):
        return None, False
    if not looks_like_listing_attempt(full_text):
        return None, False

    repaired = await repair_listing_json(provider, full_text)
    if not repaired:
        return None, False
    save_listing_revision(db, conv_id, repaired)
    ConversationRepo(db).add_message(
        conv_id,
        "system",
        "Repaired malformed listing JSON and saved it for review.",
        provider="system",
        model="",
    )
    return None, True


async def persist_chat_result(
    db: Session,
    conv_id: str,
    full_text: str,
    provider,
    *,
    provider_name: str,
    provider_model: str,
    stream_error: str,
    user_message: str,
) -> tuple[list[dict] | None, bool]:
    stream_repo = ConversationRepo(db)
    usable = full_text.strip() and not full_text.lstrip().lower().startswith("error:")
    saved = False
    operations: list[dict] | None = None
    if usable and not stream_error:
        stream_repo.add_message(conv_id, "assistant", full_text, provider=provider_name, model=provider_model)
        operations, saved = await apply_listing_payload_with_repair(
            db, conv_id, full_text, provider, user_message=user_message
        )
        if saved:
            await _maybe_resolve_vendoo_category(db, conv_id, operations=operations)
        from vendoo_studio.repositories.queries import JobRepo
        from vendoo_studio.routes.jobs import resume_completion

        for job in JobRepo(db).list_by_conversation(conv_id):
            if job.current_step == "awaiting_answers":
                try:
                    await resume_completion(job.id, db)
                except HTTPException as exc:
                    stream_repo.add_message(conv_id, "system", str(exc.detail), provider="system", model="")
                break
    elif stream_error or not full_text.strip():
        stream_repo.add_message(
            conv_id,
            "system",
            stream_error or "The listing assistant returned an empty response. Retry this prompt.",
            provider="system",
            model="",
        )

    from vendoo_studio.repositories.queries import JobRepo

    active = any(job.conversation_id == conv_id for job in JobRepo(db).get_active())
    stream_repo.update_status(conv_id, "listing" if active else "draft")
    return operations, saved
