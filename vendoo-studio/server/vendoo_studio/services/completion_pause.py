"""Pause a completion job for seller review without duplicating chat messages."""

from __future__ import annotations

from sqlalchemy.orm import Session

from vendoo_studio.repositories.queries import ConversationRepo, JobRepo


def _recent_message_covers(repo: ConversationRepo, conv_id: str, reason: str) -> bool:
    """Skip re-posting the same seller question already shown in chat."""
    needle = (reason or "").strip()
    if not needle:
        return False
    for message in reversed(repo.get_messages(conv_id)[-8:]):
        text = (message.text or "").strip()
        if not text:
            continue
        if text == needle or needle in text or text in needle:
            return True
    return False


def pause_job(db: Session, job, reason: str, gaps: list[dict], *, waiting: bool = False) -> None:
    db.refresh(job)
    if job.status == "cancelled":
        return
    job.status = "failed"
    job.current_step = "awaiting_answers" if waiting else "completion_blocked"
    job.last_error = reason
    db.commit()
    JobRepo(db).add_event(job.id, job.current_step, job.current_step, {"reason": reason, "fields": gaps})
    repo = ConversationRepo(db)
    repo.update_status(job.conversation_id, "draft")
    from vendoo_studio.routes.extension import schedule_advance_job_queue
    schedule_advance_job_queue()
    if _recent_message_covers(repo, job.conversation_id, reason):
        # Same review note already in chat — keep the pause without duplicating lines.
        return
    repo.add_message(job.conversation_id, "system", reason, provider="system", model="")
