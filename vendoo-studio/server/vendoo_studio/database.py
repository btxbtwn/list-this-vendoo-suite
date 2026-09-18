from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from vendoo_studio.config import DATABASE_PATH

engine = create_engine(
    f"sqlite:///{DATABASE_PATH}",
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(engine, "connect")
def enable_wal(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from vendoo_studio.models.conversation import Conversation  # noqa: F401
    from vendoo_studio.models.listing import Listing, ListingRevision  # noqa: F401
    from vendoo_studio.models.job import Job, JobEvent  # noqa: F401
    from vendoo_studio.models.diagnostics import DiagnosticRun, FieldObservation  # noqa: F401
    from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
    from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
    from vendoo_studio.models.catalog import (  # noqa: F401
        CategoryFieldSchema,
        CategoryNode,
        CategorySchema,
        CategoryTree,
        CategoryTreeNode,
    )

    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()


def _ensure_sqlite_columns() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    statements = []

    if "conversations" in tables:
        existing = {column["name"] for column in inspector.get_columns("conversations")}
        if "settled_at" not in existing:
            statements.append("ALTER TABLE conversations ADD COLUMN settled_at DATETIME")
        if "unsettled_at" not in existing:
            statements.append("ALTER TABLE conversations ADD COLUMN unsettled_at DATETIME")

    if "field_registry" in tables:
        existing = {column["name"] for column in inspector.get_columns("field_registry")}
        if "options_source" not in existing:
            statements.append("ALTER TABLE field_registry ADD COLUMN options_source VARCHAR")

    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
