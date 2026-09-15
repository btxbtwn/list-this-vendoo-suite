from sqlalchemy import Boolean, Column, DateTime, JSON, String, UniqueConstraint

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


class CategoryTree(Base):
    __tablename__ = "category_trees"

    marketplace = Column(String, primary_key=True)
    roots_loaded = Column(Boolean, default=False, nullable=False)
    status = Column(String, default="pending", nullable=False)
    error = Column(String)
    source = Column(String)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class CategoryTreeNode(Base):
    __tablename__ = "category_tree_nodes"

    marketplace = Column(String, primary_key=True)
    category_id = Column(String, primary_key=True)
    parent_id = Column(String, nullable=False)
    path = Column(String, nullable=False, index=True)
    label = Column(String, nullable=False)
    is_leaf = Column(Boolean, nullable=False)
    has_children = Column(Boolean, nullable=False)
    children_loaded = Column(Boolean, nullable=False, default=False)
