from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from vendoo_studio.config import is_packaged
from vendoo_studio.database import get_db
from vendoo_studio.services.chrome_bridge import chrome_executable

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.0", "service": "vendoo-studio"}


@router.get("/api/status")
def status(db: Session = Depends(get_db)):
    from vendoo_studio.models.conversation import Conversation
    from vendoo_studio.models.job import Job
    from vendoo_studio.routes.extension import extension_manager
    from vendoo_studio.services.listing_provider import provider_is_configured

    conversations = db.query(Conversation).count()
    from vendoo_studio.models.job import ACTIVE_JOB_STATUSES
    active_jobs = db.query(Job).filter(Job.status.in_(ACTIVE_JOB_STATUSES)).all()

    return {
        "version": "0.1.0",
        "provider_configured": provider_is_configured(),
        "extension_connected": extension_manager.connected,
        "active_job_id": active_jobs[0].id if active_jobs else None,
        "conversations": conversations,
        "active_jobs": len(active_jobs),
        "database_ok": True,
        "packaged": is_packaged(),
        "chrome_available": chrome_executable() is not None,
    }
