from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, Integer, String

from vendoo_studio.database import Base
from vendoo_studio.models.conversation import new_id, utcnow


class SourceBox(Base):
    """A wholesale box the seller bought. Listings point at it through
    ``Conversation.box_id``, so what the box sold for can be set against what
    it cost."""

    __tablename__ = "source_boxes"

    id = Column(String, primary_key=True, default=new_id)
    store = Column(String, nullable=False)
    title = Column(String, nullable=False)
    url = Column(String, nullable=True)
    price = Column(Float, nullable=False, default=0.0)
    shipping = Column(Float, nullable=False, default=0.0)
    pieces = Column(Integer, nullable=True)
    # What the buy list expected one piece to sell for when the box was bought,
    # so real sales can show how far off the estimates run.
    estimate_per_piece = Column(Float, nullable=True)
    bought_at = Column(DateTime, nullable=False, default=utcnow)
    created_at = Column(DateTime, default=utcnow)
