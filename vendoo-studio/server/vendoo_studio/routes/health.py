from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.0", "service": "vendoo-studio"}


@router.get("/api/status")
def status(db: Session = Depends(get_db)):
    from vendoo_studio.models.conversation import Conversation
    from vendoo_studio.models.job import Job
    from vendoo_studio.routes.extension import extension_manager
    from vendoo_studio.services.keychain import get_api_key

    conversations = db.query(Conversation).count()
    active_statuses = {"queued", "awaiting_extension", "dispatched"}
    active_jobs = db.query(Job).filter(Job.status.in_(active_statuses)).all()

    return {
        "version": "0.1.0",
        "provider_configured": bool(get_api_key()),
        "extension_connected": extension_manager.connected,
        "active_job_id": active_jobs[0].id if active_jobs else None,
        "conversations": conversations,
        "active_jobs": len(active_jobs),
        "database_ok": True,
    }
