"""Which Vendoo API sends are actually in this process.

Create and save hold a job in ``dispatched`` for the whole request, including
the model step that fills marketplace fields. That step does not touch Chrome.
If the request dies — the process restarts, the client goes away, the task is
cancelled — the row used to stay ``dispatched``. Chrome reconnect is the only
thing that used to clear it, so a dead send kept blocking the next one with
"Chrome is busy" while nothing was running.

Live sends register here. Anything ``dispatched`` on a ``vendoo_api_*`` step
that this process is not running, and that is older than a short grace, is
failed so the next Send can start.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from vendoo_studio.models.job import is_vendoo_api_step
from vendoo_studio.repositories.queries import JobRepo

log = logging.getLogger("vendoo_studio.api_job_lock")

# Long enough that a job committed and not yet claimed is not failed by a
# jobs poll in the same moment. Short enough that a dead send clears on the
# editor's next poll.
ORPHAN_GRACE = timedelta(seconds=5)

ABANDONED_SEND = "Send to Vendoo stopped before it finished. Click Send to Vendoo again."

_live_api_job_ids: set[str] = set()
# Check-and-claim for a new send. Held only across the busy check and the
# insert, never across the Chrome or model work.
_start_gate = threading.Lock()


def start_gate() -> threading.Lock:
    return _start_gate


def claim_api_job(job_id: str) -> None:
    _live_api_job_ids.add(job_id)


def release_api_job(job_id: str) -> None:
    _live_api_job_ids.discard(job_id)


def api_job_is_live(job_id: str) -> bool:
    return job_id in _live_api_job_ids


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def release_orphaned_api_jobs(db: Session, *, now: datetime | None = None) -> list[str]:
    """Fail dispatched API sends this process is not running.

    Returns the ids that were cleared. A send claimed in this process, and a
    row newer than ``ORPHAN_GRACE``, are left alone.
    """
    moment = _as_utc(now) or datetime.now(UTC)
    repo = JobRepo(db)
    cleared: list[str] = []
    for job in repo.get_running():
        if not is_vendoo_api_step(job.current_step):
            continue
        if job.id in _live_api_job_ids:
            continue
        updated = _as_utc(job.updated_at)
        if updated is not None and moment - updated < ORPHAN_GRACE:
            continue
        repo.update_status(job.id, "failed", job.current_step, error=ABANDONED_SEND)
        repo.add_event(job.id, "vendoo_api_abandoned", job.current_step, {"reason": "orphan"})
        cleared.append(job.id)
        log.info("cleared orphaned Vendoo API job %s at %s", job.id, job.current_step)
    return cleared


def abandon_api_job_if_still_running(db: Session, job_id: str) -> None:
    """Fail a send whose request ended without completing or cancelling it."""
    repo = JobRepo(db)
    job = repo.get(job_id)
    if not job or str(job.status or "") != "dispatched":
        return
    if not is_vendoo_api_step(job.current_step):
        return
    repo.update_status(job.id, "failed", job.current_step, error=ABANDONED_SEND)
    repo.add_event(job.id, "vendoo_api_abandoned", job.current_step, {"reason": "request_ended"})
