"""Seller-maintained promotion plans. These records never trigger automation."""

from sqlalchemy import JSON, Column, Date, DateTime, Float, String, Text

from vendoo_studio.database import Base
from vendoo_studio.models.conversation import new_id, utcnow


class SaleEvent(Base):
    __tablename__ = "sale_events"

    id = Column(String, primary_key=True, default=new_id)
    title = Column(String, nullable=False)
    marketplace = Column(String, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    timezone = Column(String, nullable=False)
    discount_percent = Column(Float, nullable=True)
    fee_percent = Column(Float, nullable=True)
    shipping_cost = Column(Float, nullable=True)
    minimum_profit = Column(Float, nullable=True)
    # Snapshot the chosen items so an edit or deletion cannot rewrite history.
    items = Column(JSON, nullable=False)
    status = Column(String, nullable=False, default="planned")
    notes = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
