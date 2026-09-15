from sqlalchemy import Column, DateTime, JSON, String, UniqueConstraint

from vendoo_studio.database import Base
from vendoo_studio.models.conversation import new_id, utcnow


class CategorySchema(Base):
    __tablename__ = "category_schemas"

    id = Column(String, primary_key=True, default=new_id)
    general_path = Column(String, nullable=False, index=True)
    marketplace = Column(String, nullable=False)
    category_path = Column(String, nullable=False)
    fields = Column(JSON, nullable=False)
    observed_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("general_path", "marketplace"),)


class CategoryNode(Base):
    __tablename__ = "category_nodes"

    id = Column(String, primary_key=True, default=new_id)
    marketplace = Column(String, nullable=False)
    path = Column(String, nullable=False)
    parent_path = Column(String, nullable=False, default="")
    label = Column(String, nullable=False)
    observed_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("marketplace", "path"),)
