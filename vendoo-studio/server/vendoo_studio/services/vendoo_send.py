"""Small durable send checkpoints and timings in the existing job event store."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from time import perf_counter

from sqlalchemy import inspect
from sqlalchemy.orm import object_session

from vendoo_studio.repositories.queries import JobRepo

log = logging.getLogger("vendoo_studio.vendoo_send")


def job_repo(job) -> JobRepo | None:
    if inspect(job, raiseerr=False) is None:
        return None
    session = object_session(job)
    return JobRepo(session) if session is not None else None


def pending_send(job) -> dict | None:
    repo = job_repo(job)
    return repo.pending_vendoo_send(job.conversation_id) if repo else None


def checkpoint(job, uid: str, item_id: str) -> None:
    """Commit the account and id before any remote draft write can occur."""
    repo = job_repo(job)
    if repo:
        repo.add_event(job.id, "vendoo_api_checkpoint", payload={"uid": uid, "item_id": item_id})


def record_photo_progress(db, job_id: str | None, payload: dict) -> None:
    repo = JobRepo(db)
    job = repo.get(job_id) if job_id else None
    if not job or job.status != "dispatched" or job.current_step != "vendoo_api_photos":
        return
    completed, total = payload.get("completed"), payload.get("total")
    if type(completed) is not int or type(total) is not int or not 0 <= completed <= total or total <= 0:
        return
    previous = repo.latest_event(job_id, "vendoo_api_progress")
    if previous and completed < previous.payload.get("completed", 0):
        return
    repo.add_event(job_id, "vendoo_api_progress", "vendoo_api_photos", {"completed": completed, "total": total})


@contextmanager
def measure_stage(job, stage: str):
    """One bounded timing row per job; no listing data or credentials."""
    started = perf_counter()
    ok = False
    try:
        yield
        ok = True
    finally:
        duration = round((perf_counter() - started) * 1000)
        log.info("Vendoo stage %s took %sms (ok=%s)", stage, duration, ok)
        try:
            repo = job_repo(job)
            if repo:
                previous = repo.latest_event(job.id, "vendoo_api_timing")
                timings = dict(previous.payload or {}) if previous else {}
                current = timings.get(stage) or {}
                timings[stage] = {
                    "count": int(current.get("count", 0)) + 1,
                    "total_ms": int(current.get("total_ms", 0)) + duration,
                    "last_ms": duration,
                    "ok": ok,
                }
                repo.add_event(job.id, "vendoo_api_timing", payload=timings)
        except Exception:  # noqa: BLE001 - telemetry must not fail the send
            log.warning("Could not record Vendoo stage timing", exc_info=True)
