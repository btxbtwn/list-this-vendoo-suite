"""Approved Vendoo sends run from durable job snapshots, independent of the UI."""

import logging
from types import SimpleNamespace

from fastapi import HTTPException

from vendoo_studio.database import SessionLocal
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services.send_review import photo_versions

log = logging.getLogger(__name__)


async def run_send(job_id: str) -> None:
    from vendoo_studio.routes.vendoo_api import (
        _create_claimed_draft, _finish_api_send, _save_claimed_draft,
    )
    from vendoo_studio.services.listing_generate import current_photo_analysis
    from vendoo_studio.services.listing_provider import get_listing_provider, provider_is_configured

    db = SessionLocal()
    try:
        repo = JobRepo(db)
        job = repo.get(job_id)
        if not job or job.status != "dispatched":
            return
        repo.add_event(job.id, "vendoo_api_started")
        conv_repo = ConversationRepo(db)
        conv = conv_repo.get(job.conversation_id)
        if not conv:
            raise ValueError("Listing no longer exists")
        revisions = [SimpleNamespace(id=job.approved_revision_id)]
        snapshot = dict(job.listing_snapshot)
        review = repo.latest_event(job.id, "vendoo_review")
        photos = conv_repo.get_photos(conv.id)
        current = ListingRepo(db).get_revisions(conv.id)
        if review and photo_versions(conv_repo.get_all_photos(conv.id),
                                     current[0].listing_json if current else None) != review.payload.get("photo_versions"):
            raise ValueError("Photos changed after approval. Review the listing again before sending.")
        provider = get_listing_provider() if provider_is_configured() else None
        evidence = current_photo_analysis(conv_repo, conv.id) or str(conv.notes or "")
        if job.vendoo_item_id:
            await _save_claimed_draft(
                db, conv, conv.id, job.vendoo_item_id, revisions, snapshot,
                provider, evidence, job, repo,
            )
        else:
            await _create_claimed_draft(
                db, conv, conv.id, revisions, snapshot, photos,
                provider, evidence, job, repo,
            )
    except Exception as exc:
        db.rollback()
        repo = JobRepo(db)
        job = repo.get(job_id)
        # Only a send still running is failed here; one already ended or put
        # back in the queue after an interruption keeps its state.
        if job and job.status == "dispatched":
            error = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
            repo.update_status(job_id, "failed", job.current_step, error=error)
        log.info("Queued Vendoo send ended for %s: %s", job_id, type(exc).__name__)
    finally:
        _finish_api_send(db, job_id)
        db.close()
        from vendoo_studio.services.extension_connection import schedule_advance_job_queue

        schedule_advance_job_queue()
