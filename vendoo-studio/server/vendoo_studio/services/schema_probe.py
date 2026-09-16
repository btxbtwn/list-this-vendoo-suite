from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from vendoo_studio.models.job import Job
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services.vendoo_import import merge_notes, parse_notes, vendoo_binding

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


# Vendoo keeps Save disabled on new drafts until a few general fields exist.
# First-generate probes often have category only — seed the rest from notes.
_PROBE_DEFAULT_CONDITION = "Good"


def is_schema_probe_job(job: Job | None) -> bool:
    if not job or not isinstance(job.listing_snapshot, dict):
        return False
    return bool(job.listing_snapshot.get(SCHEMA_PROBE_FLAG))


def seed_probe_general_fields(snapshot: dict, notes: str | None = None) -> dict:
    """Ensure schema-probe listings carry enough general fields for Save."""
    if not isinstance(snapshot, dict):
        return {}
    out = snapshot
    parsed = parse_notes(notes)
    if not str(out.get("condition") or "").strip():
        condition = str(parsed.get("condition") or "").strip() or _PROBE_DEFAULT_CONDITION
        out["condition"] = condition
    if not str(out.get("title") or "").strip():
        out["title"] = "Draft listing"
    if not str(out.get("zipCode") or out.get("zip_code") or "").strip():
        out["zipCode"] = "70125"
    if out.get("quantity") in (None, ""):
        out["quantity"] = 1
    return out


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
    from vendoo_studio.services.category_catalog import schema_covers_platforms
    from vendoo_studio.services.marketplaces import selected_fillable_platforms
    platforms = selected_fillable_platforms()
    # Reuse remembered field schemas across conversations — no Chrome tour needed.
    if schema_covers_platforms(db, category_path, ["general", *platforms]):
        return {"started": False, "reason": "cached", "category_path": category_path}

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
    seed_probe_general_fields(snapshot, conv.notes)
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


def _schema_from_probe_job(db: Session, job_id: str) -> dict | None:
    events = JobRepo(db).get_events(job_id)
    return next(
        (
            (event.payload or {}).get("schema")
            for event in reversed(events)
            if event.step == "discovering_schema" and (event.payload or {}).get("schema")
        ),
        None,
    )


def _validate_schema_paths(schema: dict, paths: dict, platforms: list[str]) -> None:
    required = ["general", *platforms]
    missing = [
        mp for mp in required
        if not schema.get(mp, {}).get("fields") or schema[mp].get("error")
    ]
    if missing:
        details = []
        for mp in missing:
            section = schema.get(mp) or {}
            err = section.get("error")
            details.append(f"{mp}: {err}" if err else f"{mp}: no fields")
        raise RuntimeError(
            "Category discovery did not return all selected marketplace fields "
            f"({', '.join(details)}). Retry discovery."
        )
    for marketplace, expected in paths.items():
        observed = str((schema.get(marketplace, {}).get("category") or {}).get("path") or "").strip()
        if observed and expected and observed.casefold() != expected.casefold():
            raise RuntimeError(
                f"{marketplace} category was not verified: expected {expected}, observed {observed or 'empty'}"
            )


async def prepare_generation_schema(
    db: Session,
    conv_id: str,
    provider,
    analysis: str,
    notes: str,
    *,
    on_status=None,
) -> dict:
    """Resolve a category; reuse cached schemas or kick Chrome discovery without blocking generate."""
    from vendoo_studio.routes.extension import dispatch_queued_jobs, extension_manager
    from vendoo_studio.services.category_catalog import cached_schema_payload
    from vendoo_studio.services.category_selection import select_categories
    from vendoo_studio.services.marketplaces import selected_fillable_platforms
    from vendoo_studio.services.vendoo_import import parse_notes

    def status(message: str) -> None:
        if on_status:
            on_status(message)

    override = str(parse_notes(notes).get("categoryOverride") or "").strip()
    revisions = ListingRepo(db).get_revisions(conv_id)
    seed = deepcopy(revisions[0].listing_json) if revisions else {}
    platforms = selected_fillable_platforms()
    status("Choosing marketplace categories…")
    paths = await select_categories(db, provider, analysis, notes, platforms, override)
    seed["category_path"] = paths["general"]
    seed["marketplace_categories"] = {mp: path for mp, path in paths.items() if mp != "general"}
    conv = ConversationRepo(db).get(conv_id)
    seed_probe_general_fields(seed, conv.notes if conv else notes)
    ListingRepo(db).save_revision(
        conv_id,
        seed,
        source="category_analysis",
        parent_revision_id=revisions[0].id if revisions else None,
    )

    category_path = str(seed.get("category_path") or "").strip()
    required = ["general", *platforms]
    cached = cached_schema_payload(db, category_path, required)
    if cached:
        # Prefer marketplace leaves that produced the remembered field schemas.
        seed["marketplace_categories"] = {
            mp: str((cached.get(mp) or {}).get("category", {}).get("path") or "").strip()
            for mp in platforms
            if str((cached.get(mp) or {}).get("category", {}).get("path") or "").strip()
        }
        ListingRepo(db).save_revision(
            conv_id,
            seed,
            source="category_schema_cache",
            parent_revision_id=revisions[0].id if revisions else None,
        )
        status("Using cached category fields…")
        log.info("generation schema cache hit conv=%s category=%s", conv_id, category_path)
        seed["_schema_source"] = "cache"
        return seed

    result = maybe_start_schema_probe(db, conv_id, listing=seed, reason="before_generation")
    if result.get("reason") == "cached":
        cached = cached_schema_payload(db, category_path, required)
        if cached:
            seed["_schema_source"] = "cache"
            status("Using cached category fields…")
            return seed

    job_id = result.get("job_id")
    if result.get("reason") == "already_done" and job_id:
        db.expire_all()
        schema = _schema_from_probe_job(db, job_id)
        if schema:
            try:
                job_platforms = (JobRepo(db).get(job_id).listing_snapshot or {}).get("platforms") or platforms
                _validate_schema_paths(schema, paths, job_platforms)
                seed["_schema_source"] = "prior_probe"
                status("Using discovered category fields…")
                return seed
            except RuntimeError:
                log.warning("prior probe schema incomplete for %s; rediscovering", conv_id)

    if not job_id:
        reason = str(result.get("reason") or "unknown")
        if reason in {"busy", "already_running"}:
            seed["_schema_source"] = "deferred_busy"
            seed["_schema_probe_job_id"] = result.get("active_job_id") or result.get("job_id")
            status("Generating with known fields while Chrome is busy…")
            return seed
        start_errors = {
            "cached": "Cached category fields were found but could not be loaded. Retry generation.",
            "no_category": "Category discovery could not start: no verified category path yet.",
            "conversation_not_found": "Category discovery could not start: conversation not found.",
            "error": "Category discovery could not start because of an internal Studio error. Check Studio logs.",
        }
        raise RuntimeError(start_errors.get(reason, f"Category discovery could not start: {reason}"))

    if not extension_manager.connected:
        if result.get("started"):
            job = JobRepo(db).get(job_id)
            if job and job.status in {"queued", "awaiting_extension"}:
                job.status = "failed"
                job.current_step = "discovering_schema"
                job.last_error = "Chrome disconnected before category discovery"
                db.commit()
        raise RuntimeError("Connect Chrome to discover the category fields before generating the listing.")

    # Kick Chrome discovery but do not block listing generation on it.
    status("Discovering fields in Chrome in the background…")
    if result.get("started"):
        await dispatch_queued_jobs()
    seed["_schema_source"] = "deferred_probe"
    seed["_schema_probe_job_id"] = job_id
    try:
        extension_manager.register_wait("schema:" + job_id)
    except Exception:
        log.exception("failed to register deferred schema wait for %s", job_id)
    return seed


async def await_deferred_schema(db: Session, seed: dict, *, timeout: float = 300.0) -> dict | None:
    """Wait for a deferred Chrome schema probe started during generation."""
    import asyncio
    from vendoo_studio.routes.extension import extension_manager

    job_id = str((seed or {}).get("_schema_probe_job_id") or "").strip()
    source = str((seed or {}).get("_schema_source") or "")
    if not job_id or source not in {"deferred_probe", "deferred_busy"}:
        return None
    if source == "deferred_busy":
        return None

    waiter_id = "schema:" + job_id
    waiter = extension_manager.register_wait(waiter_id)
    try:
        try:
            response = await asyncio.wait_for(waiter, timeout=timeout)
        except asyncio.TimeoutError:
            log.warning("deferred schema probe timed out for job %s", job_id)
            return None
        if not response.get("ok"):
            log.warning(
                "deferred schema probe failed for job %s: %s",
                job_id,
                response.get("error") or "unknown",
            )
            return None
    finally:
        extension_manager.cancel_wait(waiter_id)

    db.expire_all()
    return _schema_from_probe_job(db, job_id)
