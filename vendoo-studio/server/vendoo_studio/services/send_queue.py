"""Approved Vendoo sends run from durable job snapshots, independent of the UI."""

import logging
from types import SimpleNamespace

from fastapi import HTTPException

from vendoo_studio.database import SessionLocal
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo

log = logging.getLogger(__name__)


async def run_send(job_id: str) -> None:
    from vendoo_studio.routes.vendoo_api import (
        _create_claimed_draft, _finish_api_send, _save_claimed_draft,
    )
    from vendoo_studio.services.listing_generate import latest_photo_analysis
    from vendoo_studio.services.listing_provider import get_listing_provider, provider_is_configured

    db = SessionLocal()
    try:
        repo = JobRepo(db)
        job = repo.get(job_id)
        if not job or job.status != "dispatched":
            return
        conv_repo = ConversationRepo(db)
        conv = conv_repo.get(job.conversation_id)
        if not conv:
            raise ValueError("Listing no longer exists")
        revisions = [SimpleNamespace(id=job.approved_revision_id)]
        snapshot = dict(job.listing_snapshot)
        provider = get_listing_provider() if provider_is_configured() else None
        evidence = latest_photo_analysis(conv_repo.get_messages(conv.id)) or str(conv.notes or "")
        if job.vendoo_item_id:
            await _save_claimed_draft(
                db, conv, conv.id, job.vendoo_item_id, revisions, snapshot,
                provider, evidence, job, repo,
            )
        else:
            await _create_claimed_draft(
                db, conv, conv.id, revisions, snapshot, conv_repo.get_photos(conv.id),
                provider, evidence, job, repo,
            )
    except Exception as exc:
        db.rollback()
        repo = JobRepo(db)
        job = repo.get(job_id)
        if job and job.status not in {"cancelled", "failed", "completed"}:
            error = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
            repo.update_status(job_id, "failed", job.current_step, error=error)
        log.info("Queued Vendoo send ended for %s: %s", job_id, type(exc).__name__)
    finally:
        _finish_api_send(db, job_id)
        db.close()
        from vendoo_studio.routes.extension import schedule_advance_job_queue

        schedule_advance_job_queue()
