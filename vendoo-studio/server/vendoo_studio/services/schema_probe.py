from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from vendoo_studio.models.job import Job
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services.vendoo_import import merge_notes, vendoo_binding

log = logging.getLogger("vendoo_studio.schema_probe")

SCHEMA_PROBE_FLAG = "_schema_probe"
PROBE_STEPS = frozenset({
    "queued",
    "awaiting_extension",
    "opening_vendoo",
    "waiting_ready",
    "selecting_category",
    "saving_general",
    "discovering_schema",
})


def is_schema_probe_job(job: Job | None) -> bool:
    if not job or not isinstance(job.listing_snapshot, dict):
        return False
    return bool(job.listing_snapshot.get(SCHEMA_PROBE_FLAG))


def listing_for_extension(snapshot: dict | None) -> dict:
    """Strip Studio-only keys before sending listing JSON to the extension."""
    return {
        key: value
        for key, value in (snapshot or {}).items()
        if not str(key).startswith("_") and key != "platforms"
    }


def should_probe(listing: dict | None, *, previous_path: str | None = None) -> bool:
    if not isinstance(listing, dict):
        return False
    path = str(listing.get("category_path") or "").strip()
    if not path or ">" not in path:
        return False
    if previous_path and previous_path.strip() == path:
        return False
    return True


def maybe_start_schema_probe(
    db: Session,
    conv_id: str,
    *,
    listing: dict | None = None,
    reason: str = "generate",
) -> dict[str, Any]:
    """Enqueue a schema-only Vendoo job when Chrome is free and category is known.

    Never raises — generation/chat callers treat this as best-effort.
    """
    conv_repo = ConversationRepo(db)
    conv = conv_repo.get(conv_id)
    if not conv:
        return {"started": False, "reason": "conversation_not_found"}

    listing_repo = ListingRepo(db)
    revisions = listing_repo.get_revisions(conv_id)
    source_listing = listing if isinstance(listing, dict) else None
    if source_listing is None and revisions:
        source_listing = revisions[0].listing_json if isinstance(revisions[0].listing_json, dict) else None
    if not should_probe(source_listing):
        return {"started": False, "reason": "no_category"}

    category_path = str(source_listing.get("category_path") or "").strip()
    from vendoo_studio.services.marketplaces import selected_fillable_platforms
    platforms = selected_fillable_platforms()

    job_repo = JobRepo(db)
    active = job_repo.get_active()
    if active:
        running = active[0]
        if (running.conversation_id == conv_id and is_schema_probe_job(running)
                and (running.listing_snapshot or {}).get("category_path") == category_path
                and (running.listing_snapshot or {}).get("marketplace_categories") == source_listing.get("marketplace_categories")
                and (running.listing_snapshot or {}).get("platforms") == platforms):
            return {"started": False, "reason": "already_running", "job_id": running.id}
        return {
            "started": False,
            "reason": "busy",
            "active_job_id": active[0].id,
            "category_path": category_path,
        }

    # Skip duplicate probe for the same category while a recent probe job exists.
    for prior in job_repo.list_by_conversation(conv_id)[:5]:
        if not is_schema_probe_job(prior):
            continue
        prior_path = str((prior.listing_snapshot or {}).get("category_path") or "").strip()
        if prior_path != category_path:
            continue
        if (prior.listing_snapshot or {}).get("marketplace_categories") != source_listing.get("marketplace_categories"):
            continue
        if (prior.listing_snapshot or {}).get("platforms") != platforms:
            continue
        from datetime import datetime, timedelta, timezone
        if prior.created_at and prior.created_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc) - timedelta(days=1):
            continue
        if prior.status in {"queued", "awaiting_extension", "dispatched"}:
            return {"started": False, "reason": "already_running", "job_id": prior.id}
        if prior.status == "completed" and prior.current_step in {"discovering_schema", "schema_probe_done"}:
            return {"started": False, "reason": "already_done", "job_id": prior.id}

    binding = vendoo_binding(conv.notes)
    if not binding.get("vendooItemId"):
        for prior in job_repo.list_by_conversation(conv_id):
            if is_schema_probe_job(prior) and prior.vendoo_item_id and prior.vendoo_item_id != "new":
                binding = {"vendooItemId": prior.vendoo_item_id, "vendooUrl": prior.vendoo_url}
                break
    snapshot = deepcopy(source_listing)
    snapshot["platforms"] = platforms
    snapshot[SCHEMA_PROBE_FLAG] = True
    parent_id = revisions[0].id if revisions else "schema-probe"

    job = job_repo.create(
        conv_id=conv_id,
        approved_revision_id=parent_id,
        listing_snapshot=snapshot,
        vendoo_item_id=binding.get("vendooItemId"),
        vendoo_url=binding.get("vendooUrl"),
        current_step="queued",
    )
    job_repo.add_event(job.id, "created", "queued", {
        "mode": "schema_probe",
        "reason": reason,
        "category_path": category_path,
    })
    conv_repo.add_message(
        conv_id,
        "system",
        f"Discovering Vendoo marketplace fields for {category_path}…",
        provider="system",
        model="",
    )
    log.info(
        "schema probe queued job=%s conv=%s category=%s reason=%s",
        job.id,
        conv_id,
        category_path,
        reason,
    )
    return {
        "started": True,
        "job_id": job.id,
        "category_path": category_path,
        "reason": reason,
    }


def bind_probe_draft(db: Session, job: Job) -> None:
    """Persist the draft created during schema probe onto the conversation notes."""
    item_id = str(job.vendoo_item_id or "").strip()
    url = str(job.vendoo_url or "").strip()
    if not item_id and not url:
        return
    conv_repo = ConversationRepo(db)
    conv = conv_repo.get(job.conversation_id)
    if not conv:
        return
    existing = vendoo_binding(conv.notes)
    if existing.get("vendooItemId") == item_id and (not url or existing.get("vendooUrl") == url):
        return
    updates: dict[str, Any] = {}
    if item_id:
        updates["vendooItemId"] = item_id
    if url:
        updates["vendooUrl"] = url
    elif item_id:
        updates["vendooUrl"] = f"https://web.vendoo.co/app/item/{item_id}"
    conv.notes = merge_notes(conv.notes, updates)
    db.commit()


async def kickoff_schema_probe(conv_id: str, listing: dict | None, *, reason: str = "generate") -> dict[str, Any]:
    """Create a probe job (if eligible) and ask the extension dispatcher to run it."""
    from vendoo_studio.database import SessionLocal
    from vendoo_studio.routes.extension import dispatch_queued_jobs

    db = SessionLocal()
    try:
        result = maybe_start_schema_probe(db, conv_id, listing=listing, reason=reason)
        if result.get("started"):
            await dispatch_queued_jobs()
        elif result.get("reason") == "busy":
            log.info("schema probe skipped for %s: another job is active", conv_id)
        return result
    except Exception:
        log.exception("schema probe kickoff failed for %s", conv_id)
        return {"started": False, "reason": "error"}
    finally:
        db.close()


async def prepare_generation_schema(db: Session, conv_id: str, provider, analysis: str, notes: str) -> dict:
    """Resolve a category and await discovery before asking for the full listing."""
    import asyncio
    from vendoo_studio.routes.extension import dispatch_queued_jobs, extension_manager
    from vendoo_studio.services.category_selection import select_categories
    from vendoo_studio.services.marketplaces import selected_fillable_platforms
    from vendoo_studio.services.vendoo_import import parse_notes

    if not extension_manager.connected:
        raise RuntimeError("Connect Chrome to discover the category fields before generating the listing.")
    override = str(parse_notes(notes).get("categoryOverride") or "").strip()
    revisions = ListingRepo(db).get_revisions(conv_id)
    seed = deepcopy(revisions[0].listing_json) if revisions else {}
    paths = await select_categories(db, provider, analysis, notes, selected_fillable_platforms(), override)
    seed["category_path"] = paths["general"]
    seed["marketplace_categories"] = {mp: path for mp, path in paths.items() if mp != "general"}
    ListingRepo(db).save_revision(conv_id, seed, source="category_analysis",
                                 parent_revision_id=revisions[0].id if revisions else None)

    result = maybe_start_schema_probe(db, conv_id, listing=seed, reason="before_generation")
    job_id = result.get("job_id")
    if not job_id:
        raise RuntimeError("Category discovery could not start: " + str(result.get("reason")))
    if result.get("reason") != "already_done":
        waiter_id = "schema:" + job_id
        waiter = extension_manager.register_wait(waiter_id)
        try:
            if result.get("started"):
                await dispatch_queued_jobs()
            response = await asyncio.wait_for(waiter, timeout=300)
            if not response.get("ok"):
                raise RuntimeError(response.get("error") or "Category field discovery failed.")
        finally:
            extension_manager.cancel_wait(waiter_id)
    db.expire_all()
    events = JobRepo(db).get_events(job_id)
    schema = next(((event.payload or {}).get("schema") for event in reversed(events)
                   if event.step == "discovering_schema" and (event.payload or {}).get("schema")), None)
    platforms = (JobRepo(db).get(job_id).listing_snapshot or {}).get("platforms") or []
    if not schema or any(not schema.get(mp, {}).get("fields") or schema[mp].get("error") for mp in ["general", *platforms]):
        raise RuntimeError("Category discovery did not return all selected marketplace fields. Retry discovery.")
    for marketplace, expected in paths.items():
        observed = str((schema.get(marketplace, {}).get("category") or {}).get("path") or "").strip()
        if observed.casefold() != expected.casefold():
            raise RuntimeError(f"{marketplace} category was not verified: expected {expected}, observed {observed or 'empty'}")
    return seed
