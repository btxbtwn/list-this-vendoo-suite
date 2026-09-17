from __future__ import annotations


from sqlalchemy import Column, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

from vendoo_studio.database import Base
from vendoo_studio.models.conversation import new_id, utcnow


class Listing(Base):
    __tablename__ = "listings"

    conversation_id = Column(String, ForeignKey("conversations.id"), primary_key=True)
    current_revision_id = Column(String, nullable=True)
    validation_status = Column(String, nullable=True)
    validation_errors = Column(JSON, nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    conversation = relationship("Conversation", back_populates="listing")


class ListingRevision(Base):
    __tablename__ = "listing_revisions"

    id = Column(String, primary_key=True, default=new_id)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False, index=True)
    listing_json = Column(JSON, nullable=False)
    source = Column(String, nullable=False)
    parent_revision_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
