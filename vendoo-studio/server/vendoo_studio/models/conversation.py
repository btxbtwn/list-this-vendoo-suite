from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, String, Text, DateTime, Enum, Integer, Float, ForeignKey, JSON, Boolean
from sqlalchemy.orm import relationship

from vendoo_studio.database import Base


def new_id():
    return uuid.uuid4().hex[:12]


def utcnow():
    return datetime.now(timezone.utc)


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=new_id)
    title = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String, default="draft")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
    photos = relationship("Photo", back_populates="conversation", cascade="all, delete-orphan")
    listing = relationship("Listing", back_populates="conversation", uselist=False, cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=new_id)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False)
    role = Column(String, nullable=False)
    text = Column(Text, nullable=False)
    provider = Column(String, nullable=True)
    model = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    conversation = relationship("Conversation", back_populates="messages")


class Photo(Base):
    __tablename__ = "photos"

    id = Column(String, primary_key=True, default=new_id)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False)
    original_filename = Column(String, nullable=False)
    stored_filename = Column(String, nullable=False)
    mime_type = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    display_order = Column(Integer, nullable=False, default=0)
    checksum = Column(String, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    conversation = relationship("Conversation", back_populates="photos")
