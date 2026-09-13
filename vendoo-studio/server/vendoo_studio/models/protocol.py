from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


class MessageType(str, enum.Enum):
    CONNECTION_ACCEPTED = "connection.accepted"
    JOB_START = "job.start"
    JOB_RETRY = "job.retry"
    JOB_CANCEL = "job.cancel"
    JOB_FILL_FIELDS = "job.fill_fields"
    JOB_VENDOO_GET = "job.vendoo_get"
    JOB_OPEN_LISTING = "job.open_listing"
    DIAGNOSTIC_ACK = "diagnostic.ack"
    EXTENSION_RELOAD = "extension.reload"
    PING = "ping"


class ExtMessageType(str, enum.Enum):
    EXTENSION_READY = "extension.ready"
    JOB_ACCEPTED = "job.accepted"
    JOB_PROGRESS = "job.progress"
    JOB_STEP_COMPLETED = "job.step_completed"
    JOB_STEP_FAILED = "job.step_failed"
    JOB_CANCELLED = "job.cancelled"
    JOB_COMPLETED = "job.completed"
    JOB_VENDOO_ITEM = "job.vendoo_item"
    JOB_PREVIEW_FRAME = "job.preview_frame"
    DIAGNOSTIC_OBSERVED = "diagnostic.observed"
    PONG = "pong"


class ProtocolMessage(BaseModel):
    version: int = 1
    type: str
    message_id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:12])
    job_id: Optional[str] = None
    sent_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload: dict[str, Any] = Field(default_factory=dict)


class JobStartPayload(BaseModel):
    job_id: str
    listing: dict[str, Any]
    photos: list[dict[str, str]]
    options: dict[str, Any]


class StepResult(BaseModel):
    ok: bool
    step: str
    fields: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    vendoo_item_id: Optional[str] = None
    vendoo_url: Optional[str] = None
