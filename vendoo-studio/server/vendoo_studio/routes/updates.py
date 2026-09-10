from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.models.job import ACTIVE_JOB_STATUSES, Job
from vendoo_studio.services import updates as update_service
from vendoo_studio.services.updates import UpdateBlocked

router = APIRouter(prefix="/api/updates", tags=["updates"])


def _require_no_active_job(db: Session) -> None:
    active = db.query(Job).filter(Job.status.in_(ACTIVE_JOB_STATUSES)).first()
    if active:
        raise HTTPException(409, "Finish or cancel the active listing job before updating.")


@router.get("")
def update_status():
    return update_service.check_for_updates()


@router.post("/apply")
def apply_update(db: Session = Depends(get_db)):
    _require_no_active_job(db)
    try:
        result = update_service.apply_update()
    except UpdateBlocked as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc

    if result.get("updated"):
        update_service.schedule_restart()
        result["reloading"] = True
    return result
