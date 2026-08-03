from __future__ import annotations

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, Integer,UniqueConstraint

from vendoo_studio.database import Base
from vendoo_studio.models.conversation import new_id, utcnow


class DiagnosticRun(Base):
    __tablename__ = "diagnostic_runs"

    id = Column(String, primary_key=True, default=new_id)
    observation_id = Column(String, nullable=False, unique=True)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False, index=True)
    step = Column(String, nullable=False)
    collector_version = Column(String, nullable=False)
    mode = Column(String, nullable=False)
    url = Column(String, nullable=True)
    title = Column(String, nullable=True)
    timestamp = Column(String, nullable=True)
    field_count = Column(Integer, default=0)
    dropdown_count = Column(Integer, default=0)
    dropdowns_with_options = Column(Integer, default=0)
    live_dropdowns_with_options = Column(Integer, default=0)
    total_dropdown_options = Column(Integer, default=0)
    expanded_sections = Column(JSON, nullable=True)
    headings = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("observation_id", name="uq_diagnostic_observation_id"),
    )


class FieldObservation(Base):
    __tablename__ = "field_observations"

    id = Column(String, primary_key=True, default=new_id)
    diagnostic_run_id = Column(String, ForeignKey("diagnostic_runs.id"), nullable=False, index=True)
    observation_id = Column(String, nullable=False, index=True)
    label = Column(String, nullable=True)
    label_sources = Column(JSON, nullable=True)
    section_path = Column(JSON, nullable=True)
    selector = Column(String, nullable=True)
    tag = Column(String, nullable=True)
    control_type = Column(String, nullable=True)
    role = Column(String, nullable=True)
    name = Column(String, nullable=True)
    control_id = Column(String, nullable=True)
    placeholder = Column(String, nullable=True)
    classes = Column(String, nullable=True)
    is_dropdown = Column(Integer, default=0)
    option_count = Column(Integer, default=0)
    options = Column(JSON, nullable=True)
    options_source = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
