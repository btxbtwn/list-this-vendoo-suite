from __future__ import annotations

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, Integer

from vendoo_studio.database import Base
from vendoo_studio.models.conversation import new_id, utcnow

ACTIVE_JOB_STATUSES = ("queued", "awaiting_extension", "dispatched")
DISPATCHABLE_JOB_STATUSES = ("queued", "awaiting_extension")


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
