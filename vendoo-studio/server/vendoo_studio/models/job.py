from __future__ import annotations

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, Integer

from vendoo_studio.database import Base
from vendoo_studio.models.conversation import new_id, utcnow

ACTIVE_JOB_STATUSES = ("queued", "awaiting_extension", "dispatched")
DISPATCHABLE_JOB_STATUSES = ("queued", "awaiting_extension")
RUNNING_JOB_STATUSES = ("dispatched",)
TERMINAL_JOB_STATUSES = ("completed", "cancelled", "failed", "imported")


def is_terminal_job_status(status: str | None) -> bool:
    return str(status or "") in TERMINAL_JOB_STATUSES


def is_vendoo_api_step(step: str | None) -> bool:
    """True for API create/save work — never hand these to the form-filler."""
    return str(step or "").startswith("vendoo_api")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=new_id)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False)
    approved_revision_id = Column(String, nullable=False)
    listing_snapshot = Column(JSON, nullable=False)
    status = Column(String, default="queued")
    current_step = Column(String, nullable=True)
    vendoo_item_id = Column(String, nullable=True)
    vendoo_url = Column(String, nullable=True)
    attempt_count = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class JobEvent(Base):
    __tablename__ = "job_events"

    id = Column(String, primary_key=True, default=new_id)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False, default=0)
    event_type = Column(String, nullable=False)
    step = Column(String, nullable=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class VendooDraftCache(Base):
    """The last Vendoo status Studio saw for a job — one row, status only.

    This used to be an appended ``job_events`` row carrying the whole Vendoo
    item. Sync writes one on every pull, an item is tens of kilobytes, and the
    table grew past 9 GB before anyone noticed. Nothing reads the rest of the
    item back from here, so nothing else is kept.
    """

    __tablename__ = "vendoo_draft_cache"

    job_id = Column(String, ForeignKey("jobs.id"), primary_key=True)
    item_id = Column(String, nullable=True)
    url = Column(String, nullable=True)
    source = Column(String, nullable=True)
    step = Column(String, nullable=True)
    payload = Column(JSON, nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
