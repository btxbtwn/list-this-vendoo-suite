"""Ad spend the seller copied from a marketplace's ads dashboard."""

from sqlalchemy import Column, Date, DateTime, Float, Integer, String, Text

from vendoo_studio.database import Base
from vendoo_studio.models.conversation import new_id, utcnow


class AdSpend(Base):
    """What one ads programme cost over a stretch of days, and what its own
    dashboard says it sold. Poshmark Promoted Closet and Etsy Ads have no API
    Studio can read, so these figures are typed in, never fetched."""

    __tablename__ = "ad_spend"

    id = Column(String, primary_key=True, default=new_id)
    marketplace = Column(String, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    spend = Column(Float, nullable=False)
    clicks = Column(Integer, nullable=True)
    # Orders and revenue the dashboard attributes to the ads; organic sales are not in them.
    orders = Column(Integer, nullable=True)
    revenue = Column(Float, nullable=True)
    notes = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
