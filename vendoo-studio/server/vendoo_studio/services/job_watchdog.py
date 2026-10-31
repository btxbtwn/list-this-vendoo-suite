"""Fail automation jobs that died or went quiet, so the next one can start.

One Chrome job runs at a time and approved Sends wait behind it in a FIFO
queue. A job left ``dispatched`` holds that slot, keeps its listing on the busy
``listing`` label, and keeps the editor's card on "Updating…". Each stall used
to get its own fix in whichever request noticed it. This sweep is the one place
that frees the slot, on startup and every ``SWEEP_INTERVAL_SEC``:

- **dead** — a Vendoo API send this process is not running (Studio quit or
  restarted mid-send). Failed once it is ``ORPHAN_GRACE`` old, which covers a
  job committed a moment before its worker claims it.
- **silent** — any dispatched job that has not been heard from for
  ``STALL_AFTER``. Every step writes the job or one of its events as it moves
  (each Chrome op records a timing, the extension reports progress), and the
  longest single wait inside a send is Chrome's 240s op timeout or a model's
  5-minute idle limit, so ten minutes of silence is a stuck job.

The watchdog only marks a job failed and stops what is still waiting on it. It
never sends, publishes or delists. The one thing it starts again is a dead send:
that send is queued once more (``JobRepo.requeue_interrupted_send``), and the
resumed run picks up its checkpointed draft instead of creating a second one. The listing's label follows from
the failed job in ``ConversationRepo.reconcile_job_statuses``; the next queued
Send starts because a failed job frees the slot, as the queue already does.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from vendoo_studio.models.job import ABANDONED_SEND, JobEvent, is_vendoo_api_step
from vendoo_studio.repositories.queries import JobRepo
from vendoo_studio.services.api_job_lock import api_job_is_live

log = logging.getLogger("vendoo_studio.job_watchdog")

ORPHAN_GRACE = timedelta(seconds=5)
STALL_AFTER = timedelta(minutes=10)
SWEEP_INTERVAL_SEC = 15.0

STALLED_JOB = (
    "Anteroom heard nothing from this job for 10 minutes and stopped it. "
    "Check the draft in Vendoo, then try again."
)

_task: asyncio.Task | None = None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _last_heard(db: Session, jobs) -> dict[str, datetime | None]:
    """Newest of each job's own update and its newest event."""
    newest_event = dict(
        db.query(JobEvent.job_id, func.max(JobEvent.created_at))
        .filter(JobEvent.job_id.in_([job.id for job in jobs]))
        .group_by(JobEvent.job_id)
        .all()
    )
    heard: dict[str, datetime | None] = {}
    for job in jobs:
        stamps = [stamp for stamp in (_as_utc(job.updated_at), _as_utc(newest_event.get(job.id))) if stamp]
        heard[job.id] = max(stamps) if stamps else None
    return heard


def _stop_waiting_on(job_id: str) -> None:
    """Unblock work still awaiting this job, so its worker ends at its next step.

    Cancels loop futures and tasks, so it runs on the event loop.
    """
    from vendoo_studio.services.extension_connection import extension_manager
    from vendoo_studio.services.listing_completion import cancel_completion

    extension_manager.cancel_waits_for_job(job_id)
    cancel_completion(job_id)


def fail_stalled_jobs(db: Session, *, now: datetime | None = None) -> list[str]:
    """Fail dead and silent dispatched jobs. Returns the ids failed.

    Database work only, so ``sweep`` can run it off the event loop: a locked
    database must not freeze the server while this waits on it. Stopping what
    still waits on a failed job happens back on the loop, in ``sweep``.
    """
    repo = JobRepo(db)
    running = repo.get_running()
    if not running:
        return []
    moment = _as_utc(now) or datetime.now(UTC)
    heard = _last_heard(db, running)
    failed: list[str] = []
    for job in running:
        last = heard[job.id]
        quiet = moment - last if last else STALL_AFTER
        native = str(job.current_step or "").startswith("native_")
        if native and api_job_is_live(job.id):
            # A direct listing job keeps its own deadlines and must keep the slot
            # until Chrome or the marketplace answers.
            continue
        if native and quiet >= ORPHAN_GRACE:
            error, reason = "Marketplace action interrupted. Check its result before trying again.", "native_interrupted"
        elif is_vendoo_api_step(job.current_step) and not api_job_is_live(job.id) and quiet >= ORPHAN_GRACE:
            error, reason = ABANDONED_SEND, "dead"
        elif quiet >= STALL_AFTER:
            error, reason = STALLED_JOB, "silent"
        else:
            continue
        step = job.current_step
        updated = repo.update_status(job.id, "failed", step, error=error)
        if updated is None or updated.status != "failed" or updated.last_error != error:
            continue
        repo.add_event(job.id, "watchdog_failed", step, {"reason": reason, "quiet_sec": int(quiet.total_seconds())})
        if native:
            from vendoo_studio.services.native_marketplaces import mark_interrupted

            mark_interrupted(db, job.id)
            from vendoo_studio.services.listing_promotions import mark_interrupted as promotions_interrupted

            promotions_interrupted(db, job.id)
        if reason == "dead":
            # Nothing in this process runs it, so resuming cannot double up.
            repo.requeue_interrupted_send(job.id)
        failed.append(job.id)
        log.warning("Failed %s job %s at %s after %ds", reason, job.id, step, int(quiet.total_seconds()))
    return failed


async def sweep() -> list[str]:
    """One pass: fail what is stuck, tell the extension, start the next queued Send."""
    from vendoo_studio.database import SessionLocal
    from vendoo_studio.models.protocol import ProtocolMessage
    from vendoo_studio.services.extension_connection import extension_manager
    from vendoo_studio.services.native_marketplaces import reconcile_then_dispatch

    def fail_in_session() -> list[str]:
        with SessionLocal() as db:
            return fail_stalled_jobs(db)

    failed = await asyncio.to_thread(fail_in_session)
    for job_id in failed:
        _stop_waiting_on(job_id)
        await extension_manager.send_message(ProtocolMessage(
            type="job.cancel", job_id=job_id, payload={"job_id": job_id},
        ).model_dump(mode="json"))
    if failed:
        # A stalled List or Update left its result unconfirmed: read it now
        # (read-only), then start the next queued job.
        await reconcile_then_dispatch()
    return failed


async def _watch() -> None:
    from vendoo_studio.services.native_marketplaces import reconcile

    try:
        await sweep()
        # Direct listings a restart cut off: read their results (eBay and Etsy
        # here; Chrome's when it connects). Never writes.
        await reconcile(chrome=False)
    except Exception:  # noqa: BLE001 - startup reconcile must not stop the watchdog
        log.exception("Startup reconcile failed")
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SEC)
        try:
            await sweep()
        except Exception:  # noqa: BLE001 - one bad pass must not stop the watchdog
            log.exception("Job watchdog pass failed")


def start_job_watchdog() -> asyncio.Task:
    """Sweep now, then on an interval. Call from the running event loop."""
    global _task
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(_watch())
    return _task


def stop_job_watchdog() -> None:
    if _task is not None and not _task.done():
        _task.cancel()
