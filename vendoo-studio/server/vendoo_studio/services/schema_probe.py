from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from vendoo_studio.models.job import Job
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services.vendoo_import import merge_notes, parse_notes, vendoo_binding
from datetime import UTC

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


async def api_category_schemas(listing: dict) -> dict[str, dict]:
    """Field schemas for this listing's leaves, straight from Vendoo.

    Empty when nothing could be resolved or fetched, which is the signal to
    fall back to discovering them through a browser. A marketplace Vendoo has
    no schema for is not a reason to probe the ones it does.
    """
    from types import SimpleNamespace

    from vendoo_studio.services.category_fields import listing_category_ids
    from vendoo_studio.services.vendoo_create import fetch_listing_specifics

    if not listing_category_ids(listing):
        return {}
    try:
        specifics = await fetch_listing_specifics(SimpleNamespace(id=None), listing)
    except Exception:  # noqa: BLE001 - a probe is the fallback, not a failure
        log.info("category specifics unavailable; falling back to discovery", exc_info=True)
        return {}
    return {mp: fields for mp, fields in (specifics or {}).items() if fields}


async def mapped_marketplace_paths(general_path: str, platforms: list[str]) -> dict[str, str]:
    """Ask Vendoo which category each marketplace uses for this general one.

    Breadcrumbs, because that is what the form filler selects in Vendoo's UI.
    Empty when the general category is not in the local tree or the browser is
    not there to ask, so the caller can fall back.
    """
    from types import SimpleNamespace

    from vendoo_studio.services.vendoo_api import category_from_hit
    from vendoo_studio.services.vendoo_create import _hits_by_mapping, tree_leaf

    if not general_path or not platforms:
        return {}
    general = category_from_hit(tree_leaf("general", general_path), general_path)
    if not (general and general.get("id")):
        return {}
    targets = [(mp, mp, "") for mp in platforms]
    try:
        hits = await _hits_by_mapping(SimpleNamespace(id=None), general, targets)
    except Exception:  # noqa: BLE001 - generation should not fail over this
        log.info("category mapping unavailable during generate", exc_info=True)
        return {}
    out: dict[str, str] = {}
    for marketplace, hit in hits.items():
        labels = hit.get("all_category_label") or hit.get("displayPath") or []
        if isinstance(labels, list) and labels:
            out[marketplace] = " > ".join(str(part) for part in labels)
    return out


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
        from datetime import datetime, timedelta
        if prior.created_at and prior.created_at.replace(tzinfo=UTC) < datetime.now(UTC) - timedelta(days=1):
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
    status("Choosing a category…")
    # One question, not six: the model settles the general category and Vendoo
    # maps it to each marketplace. Asking it to pick for every tree at once put
    # ~90 candidates in one prompt, which is what kept timing out and falling
    # back to keyword ranking — the fallback that chose Fastener Nuts.
    paths = await select_categories(db, provider, analysis, notes, [], override)
    seed["category_path"] = paths["general"]
    status("Matching marketplace categories…")
    mapped = await mapped_marketplace_paths(paths["general"], platforms)
    if mapped:
        from vendoo_studio.services.category_lookup import marketplace_path_fits_general
        from vendoo_studio.services.registry import map_poshmark_category_path

        mapped = {
            mp: path
            for mp, path in mapped.items()
            if marketplace_path_fits_general(paths["general"], path)
        }
        # Vendoo's mapper often returns Tank Tops for a bare Women's Tops general
        # because the leaf shares the word "tops". Remap with photo/seller text.
        if "poshmark" in mapped:
            mapped["poshmark"] = map_poshmark_category_path(
                mapped["poshmark"],
                {
                    "category_path": paths["general"],
                    "title": analysis,
                    "description": notes,
                },
            )
    missing = [mp for mp in platforms if mp not in mapped]
    if missing:
        # No mapper (no Chrome, say), or mapper returned hardware collisions —
        # ask for the missing trees. Lock the general leaf we already chose.
        fallback = await select_categories(
            db, provider, analysis, notes, missing, override or paths["general"],
        )
        seed["category_path"] = fallback.get("general") or paths["general"]
        for marketplace in missing:
            path = fallback.get(marketplace)
            if path:
                mapped[marketplace] = path
    seed["marketplace_categories"] = mapped
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
        from vendoo_studio.services.registry import map_poshmark_category_path

        seed["marketplace_categories"] = {
            mp: str((cached.get(mp) or {}).get("category", {}).get("path") or "").strip()
            for mp in platforms
            if str((cached.get(mp) or {}).get("category", {}).get("path") or "").strip()
        }
        if "poshmark" in seed["marketplace_categories"]:
            seed["marketplace_categories"]["poshmark"] = map_poshmark_category_path(
                seed["marketplace_categories"]["poshmark"],
                {
                    **seed,
                    "title": seed.get("title") or analysis,
                    "description": seed.get("description") or notes,
                },
            )
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

    # Vendoo answers what a probe used to discover. A probe drives a real
    # draft through Chrome and leaves it in the seller's account; asking the
    # category-specifics endpoint costs one request and no draft at all.
    api_specs = await api_category_schemas(seed)
    if api_specs:
        seed["_schema_source"] = "api"
        status("Using Vendoo's category fields…")
        log.info(
            "generation schema from the API for %s: %s",
            conv_id,
            ", ".join(f"{mp}:{len(fields)}" for mp, fields in sorted(api_specs.items())),
        )
        return seed

    # Vendoo answers what a browser tour used to discover, so there is nothing
    # left to discover. Generating without a schema is fine: create resolves
    # each leaf and fetches its fields then, and the gap filler works from
    # whatever is cached by that point. Driving Chrome here only ever cost a
    # throwaway draft in the seller's account and a failure mode when it broke.
    seed["_schema_source"] = "deferred"
    status("Generating with the category's own fields…")
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
        except TimeoutError:
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
