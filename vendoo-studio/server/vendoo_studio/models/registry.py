from __future__ import annotations

from sqlalchemy import Column, String, DateTime, JSON, Integer, UniqueConstraint

from vendoo_studio.database import Base
from vendoo_studio.models.conversation import new_id, utcnow


class FieldRegistry(Base):
    __tablename__ = "field_registry"

    id = Column(String, primary_key=True, default=new_id)
    marketplace = Column(String, nullable=False, index=True)
    category_path = Column(String, nullable=True, index=True)
    normalized_label = Column(String, nullable=False)
    control_type = Column(String, nullable=True)
    is_dropdown = Column(Integer, default=0)
    known_selectors = Column(JSON, default=[])
    known_options = Column(JSON, default=[])
    # How known_options was last captured. An authoritative read of an open
    # dropdown replaces the option set; anything weaker only unions into it.
    options_source = Column(String, nullable=True)
    observation_count = Column(Integer, default=0)
    first_seen = Column(DateTime, default=utcnow)
    last_seen = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "marketplace", "category_path", "normalized_label",
            name="uq_field_registry_identity"
        ),
    )
