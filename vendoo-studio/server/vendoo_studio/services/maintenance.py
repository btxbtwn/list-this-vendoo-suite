"""Where the database's space went, and the two safe ways to get it back.

Pruning removes rows nothing reads any more. ``VACUUM`` returns the pages those
rows were using to the filesystem, which SQLite otherwise keeps for reuse, so a
database that shed gigabytes of events stays the same size on disk until it
runs. It rewrites the whole file, so it runs on the way out rather than while
someone is waiting.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from vendoo_studio.config import DATABASE_PATH

log = logging.getLogger("vendoo_studio.maintenance")

TOP_TABLES = 8


def table_sizes(db: Session, *, limit: int = TOP_TABLES) -> list[dict]:
    """Bytes and rows per table, largest first.

    ``dbstat`` is a compile-time option. When SQLite was built without it there
    are still row counts to report, which is enough to point at the table that
    is growing.
    """
    known = {name for name in inspect(db.get_bind()).get_table_names() if not name.startswith("sqlite_")}
    try:
        # An index is its own row in dbstat; charge its pages to its table, or
        # the biggest table looks smaller than the index that serves it.
        rows = db.execute(text(
            """
            SELECT COALESCE(m.tbl_name, d.name) AS owner, SUM(d.pgsize) AS bytes
            FROM dbstat d LEFT JOIN sqlite_master m ON m.name = d.name
            GROUP BY owner ORDER BY bytes DESC
            """
        )).fetchall()
    except DatabaseError:
        db.rollback()
        return _row_counts(db, known, limit=limit)

    sizes = [
        {"table": str(name), "bytes": int(size_bytes or 0), "rows": _count(db, str(name))}
        for name, size_bytes in rows
        if str(name) in known
    ]
    return sizes[:limit]


def _row_counts(db: Session, known: set[str], *, limit: int) -> list[dict]:
    sizes = [{"table": name, "bytes": None, "rows": _count(db, name)} for name in sorted(known)]
    sizes.sort(key=lambda entry: entry["rows"], reverse=True)
    return sizes[:limit]


def _count(db: Session, table: str) -> int:
    # Table names come from the schema, never from a request.
    return int(db.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar() or 0)


def database_path() -> Path:
    return Path(DATABASE_PATH)


def database_bytes() -> int:
    from vendoo_studio.services.backups import database_bytes as size_on_disk

    return size_on_disk()


def prune_event_bloat(db: Session) -> dict:
    """Remove job events later builds stopped writing, and duplicate upserts."""
    from vendoo_studio.repositories.queries import JobRepo

    repo = JobRepo(db)
    drafts = repo.prune_stale_vendoo_drafts()
    duplicates = repo.prune_duplicate_upsert_events()
    return {"vendoo_drafts": drafts, "duplicate_events": duplicates, "deleted": drafts + duplicates}


def vacuum_database() -> int:
    """Rewrite the database without its free pages. Returns bytes reclaimed."""
    from vendoo_studio.database import engine

    before = database_bytes()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text("VACUUM"))
    reclaimed = before - database_bytes()
    log.info("Vacuumed the database, reclaimed %d bytes", reclaimed)
    return reclaimed


def maintenance_report(db: Session) -> dict:
    """What Settings shows: how big the database is and what is filling it."""
    return {
        "path": str(database_path()),
        "database_bytes": database_bytes(),
        "tables": table_sizes(db),
    }
