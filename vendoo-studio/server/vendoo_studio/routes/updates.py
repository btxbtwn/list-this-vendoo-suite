from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.models.job import ACTIVE_JOB_STATUSES, Job
from vendoo_studio.services import updates as update_service
from vendoo_studio.services.chrome_bridge import ChromeBridgeError, install_bundled_extension, mark_extension_reload_pending
from vendoo_studio.services.updates import UpdateBlocked

router = APIRouter(prefix="/api/updates", tags=["updates"])


def _cancel_leftover_jobs(db: Session) -> list[str]:
    jobs = db.query(Job).filter(Job.status.in_(ACTIVE_JOB_STATUSES)).all()
    cancelled: list[str] = []
    for job in jobs:
        job.status = "cancelled"
        job.current_step = None
        job.last_error = "Cancelled so Studio can update"
        cancelled.append(job.id)
    if jobs:
        db.commit()
    return cancelled


async def _after_app_replace(result: dict, cancelled_jobs: list[str]) -> dict:
    if result.get("updated"):
        generation = mark_extension_reload_pending()
        packaged = bool(result.get("packaged"))
        if not packaged:
            try:
                install_bundled_extension()
            except ChromeBridgeError:
                pass
            from vendoo_studio.routes.extension import request_extension_reload

            await request_extension_reload(generation)
        result["extension_reload"] = True
        update_service.schedule_restart(force=True)
        result["reloading"] = True
    if cancelled_jobs:
        result["cancelled_jobs"] = cancelled_jobs
    return result


@router.get("")
def update_status():
    return update_service.check_for_updates()


@router.post("/apply")
async def apply_update(db: Session = Depends(get_db)):
    cancelled_jobs = _cancel_leftover_jobs(db)
    try:
        result = update_service.apply_update()
    except UpdateBlocked as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
    return await _after_app_replace(result, cancelled_jobs)


@router.get("/progress")
def update_progress():
    return update_service.update_progress()


@router.post("/download")
async def download_update():
    try:
        return await asyncio.to_thread(update_service.prepare_update)
    except UpdateBlocked as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/restart")
async def restart_with_update(db: Session = Depends(get_db)):
    if update_service.update_progress().get("status") != "downloaded":
        raise HTTPException(409, "Download the update before restarting to install it.")
    cancelled_jobs = _cancel_leftover_jobs(db)
    try:
        result = update_service.install_prepared_update()
    except UpdateBlocked as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
    return await _after_app_replace(result, cancelled_jobs)


@router.post("/reinstall")
async def reinstall_app(db: Session = Depends(get_db)):
    cancelled_jobs = _cancel_leftover_jobs(db)
    try:
        result = update_service.reinstall_app()
    except UpdateBlocked as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
    return await _after_app_replace(result, cancelled_jobs)
