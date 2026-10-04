from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer, String, Text

from vendoo_studio.database import Base
from vendoo_studio.models.conversation import new_id, utcnow


class ScoutCheck(Base):
    """One "is this worth buying?" check from photos taken while sourcing.

    Kept after the decision, so a check that became a listing can later be set
    against what the item actually sold for."""

    __tablename__ = "scout_checks"

    id = Column(String, primary_key=True, default=new_id)
    status = Column(String, nullable=False, default="checking")  # checking | done | failed
    asking_price = Column(Float, nullable=True)
    photos = Column(JSON, nullable=False, default=list)  # stored filenames, in order
    title = Column(String, nullable=True)
    analysis = Column(Text, nullable=True)
    comps = Column(Text, nullable=True)
    estimate = Column(Float, nullable=True)  # expected sale price
    comps_count = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    decision = Column(String, nullable=True)  # bought | passed
    conversation_id = Column(
        String, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    created_at = Column(DateTime, default=utcnow)
    decided_at = Column(DateTime, nullable=True)
