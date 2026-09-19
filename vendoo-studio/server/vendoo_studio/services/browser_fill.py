"""Type values into the Vendoo form from the browser preview.

The only writer left that touches a form. Studio's own push to Vendoo — create
and save — is a Vendoo API call (``services/vendoo_create.py``); generation
stops at a saved listing and reaches Vendoo not at all. What remains here is
the seller pointing at a field in the browser preview and asking chat to fix
it, which is a request to act on the form they are looking at.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy.orm import Session

from vendoo_studio.repositories.queries import ConversationRepo, JobRepo

log = logging.getLogger(__name__)

FILL_WAIT_TIMEOUT_SEC = 600.0


async def _wait_for_fill(job_id: str, db_factory) -> tuple[bool, str | None]:
    deadline = asyncio.get_running_loop().time() + FILL_WAIT_TIMEOUT_SEC
    while asyncio.get_running_loop().time() < deadline:
        db = db_factory()
        try:
            job = JobRepo(db).get(job_id)
            if not job:
                return False, "Job not found"
            if job.status == "completed" and job.current_step == "fields_applied":
                return True, None
            if job.status == "failed":
                return False, job.last_error or "Apply on Vendoo failed"
        finally:
            db.close()
        await asyncio.sleep(0.75)
    return False, "Timed out waiting for Vendoo to finish applying values"


async def apply_patches(
    db: Session,
    job,
    listing: dict,
    patches: list[dict],
    *,
    announce: bool = True,
) -> tuple[bool, str | None]:
    from vendoo_studio.routes.extension import dispatch_fill_fields, extension_manager
    from vendoo_studio.database import SessionLocal

    if not patches:
        return True, None
    if not extension_manager.connected:
        return False, "Chrome is not connected"
    active = [item for item in JobRepo(db).get_active() if item.id != job.id]
    if active:
        return False, "Another automation job is already running"

    platforms = (job.listing_snapshot or {}).get("platforms") or []
    job.listing_snapshot = {**listing, "platforms": platforms}
    job.status = "dispatched"
    job.current_step = "filling_fields"
    job.last_error = None
    db.commit()
    JobRepo(db).add_event(
        job.id,
        "browser_fill",
        "filling_fields",
        {"count": len(patches), "patches": patches[:20]},
    )

    sent = await dispatch_fill_fields(job, patches, verify=False, read_item=True)
    if not sent:
        job.status = "failed"
        job.current_step = "filling_fields"
        job.last_error = "Could not reach the Chrome extension"
        db.commit()
        return False, job.last_error

    ok, error = await _wait_for_fill(job.id, SessionLocal)
    db.refresh(job)
    if ok and announce:
        ConversationRepo(db).add_message(
            job.conversation_id,
            "system",
            f"Applied {len(patches)} value(s) onto the Vendoo draft. Review Fields, then Send when ready.",
            provider="system",
            model="",
        )
    return ok, error
