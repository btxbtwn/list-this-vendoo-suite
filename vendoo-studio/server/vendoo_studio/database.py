from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from vendoo_studio.config import DATABASE_PATH

# SQLite serialises writers. Studio writes from the request path *and* from
# background sweeps (Vendoo label sync, watch, bulk import), so a chat send can
# arrive while a sweep holds the write lock. sqlite3's stock 5s busy timeout is
# short enough that a Chrome round-trip inside a sweep pushed sends over it, and
# the seller saw the prompt die with "database is locked". Wait instead.
BUSY_TIMEOUT_SEC = 30

engine = create_engine(
    f"sqlite:///{DATABASE_PATH}",
    connect_args={"check_same_thread": False, "timeout": BUSY_TIMEOUT_SEC},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(engine, "connect")
def enable_wal(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    # connect_args only covers the driver's own waiting; the pragma is what the
    # engine honours on statements it issues outside that path.
    cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_SEC * 1000}")
    cursor.close()


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def load_models() -> None:
    """Import every model so ``Base.metadata`` describes the whole schema."""
    from vendoo_studio.models.conversation import Conversation  # noqa: F401
    from vendoo_studio.models.listing import Listing, ListingRevision  # noqa: F401
    from vendoo_studio.models.job import Job, JobEvent, VendooDraftCache  # noqa: F401
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


def init_db():
    """Bring the database to the schema this build expects.

    Delegates to the migration runner, which snapshots before it changes
    anything and refuses a database written by a newer build.
    """
    from vendoo_studio.services.schema_migrations import ensure_schema

    load_models()
    ensure_schema(engine)


# Columns added to tables that had already shipped. ``create_all`` only creates
# whole tables, so a column added to an existing one never reaches a database
# built before it landed unless it is named here. Adding a column to a model
# without adding it here leaves older databases short of it, and the mismatch
# only shows up later as a query error.
BACKFILLED_COLUMNS: dict[str, dict[str, str]] = {
    "conversations": {
        "settled_at": "DATETIME",
        "unsettled_at": "DATETIME",
    },
    "field_registry": {
        "options_source": "VARCHAR",
    },
}


def _ensure_sqlite_columns(bind=None) -> None:
    target = bind if bind is not None else engine
    inspector = inspect(target)
    tables = set(inspector.get_table_names())
    statements = []

    for table, columns in BACKFILLED_COLUMNS.items():
        if table not in tables:
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        statements += [
            f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"
            for column, sql_type in columns.items()
            if column not in existing
        ]

    if not statements:
        return
    with target.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
