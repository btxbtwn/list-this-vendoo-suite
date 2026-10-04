from __future__ import annotations

from sqlalchemy import JSON, Column, Date, DateTime, Integer, String

from vendoo_studio.database import Base
from vendoo_studio.models.conversation import new_id, utcnow


class SaleEvent(Base):
    """A marketplace sale the seller joined, like Depop's or Etsy's sitewide
    sales. A sale on one of its marketplaces between its first and last day
    counts as an event sale."""

    __tablename__ = "sale_events"

    id = Column(String, primary_key=True, default=new_id)
    name = Column(String, nullable=False)
    starts_on = Column(Date, nullable=False)
    ends_on = Column(Date, nullable=False)
    discount_percent = Column(Integer, nullable=True)
    marketplaces = Column(JSON, nullable=False, default=list)  # marketplace ids; empty means all
    created_at = Column(DateTime, default=utcnow)
