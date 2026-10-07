"""Seller corrections and observed outcomes, separate from editable listings."""
from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, UniqueConstraint

from vendoo_studio.database import Base
from vendoo_studio.models.conversation import new_id, utcnow


class ListingCorrection(Base):
    __tablename__ = "listing_corrections"

    id = Column(String, primary_key=True, default=new_id)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False, index=True)
    revision_id = Column(String, nullable=False)
    source = Column(String, nullable=False, default="user_form")
    category_path = Column(String, nullable=False)
    brand = Column(String, nullable=False)
    changes = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class SaleSnapshot(Base):
    __tablename__ = "sale_snapshots"
    __table_args__ = (UniqueConstraint("conversation_id", "sale_key"),)

    id = Column(String, primary_key=True, default=new_id)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False, index=True)
    sale_key = Column(String, nullable=False)
    listing = Column(JSON, nullable=False)
    source = Column(String, nullable=False)
    observed_at = Column(DateTime, nullable=False, default=utcnow)


class ListingEvidence(Base):
    __tablename__ = "listing_evidence"

    conversation_id = Column(String, ForeignKey("conversations.id"), primary_key=True)
    shipping = Column(JSON, nullable=True)
    engagement = Column(JSON, nullable=True)
