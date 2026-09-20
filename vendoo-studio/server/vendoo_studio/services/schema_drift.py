"""Report where a SQLite file's schema differs from the models.

``init_db`` carries a database forward by creating absent tables and adding the
handful of columns named in ``_ensure_sqlite_columns``. Neither step covers a
renamed column, a changed type, or a backfill, and nothing fails loudly when a
gap is left behind: the mismatch surfaces later as a query error. This reports
the gap directly so a database that has sat through several updates can be
checked instead of assumed.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from vendoo_studio.config import DATABASE_PATH
from vendoo_studio.database import BACKFILLED_COLUMNS, Base, load_models


@dataclass(frozen=True)
class Drift:
    """What the models expect that the database does not have, and vice versa."""

    missing_tables: tuple[str, ...]
    missing_columns: tuple[str, ...]
    unknown_tables: tuple[str, ...]

    @property
    def unhealed_columns(self) -> tuple[str, ...]:
        """Missing columns that starting Studio will not add.

        ``create_all`` adds absent tables, so those always heal. A missing
        column heals only when ``BACKFILLED_COLUMNS`` names it.
        """
        return tuple(
            name
            for name in self.missing_columns
            if name.split(".", 1)[1] not in BACKFILLED_COLUMNS.get(name.split(".", 1)[0], {})
        )

    @property
    def healed_by_init_db(self) -> bool:
        """True when a normal startup closes every gap found."""
        return not self.unhealed_columns

    @property
    def clean(self) -> bool:
        return not self.missing_tables and not self.missing_columns


def _database_schema(path: Path) -> dict[str, set[str]]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
            if not row[0].startswith("sqlite_")
        ]
        return {
            table: {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
            for table in tables
        }
    finally:
        connection.close()


def inspect_database(path: str | Path | None = None) -> Drift:
    """Compare the models against the database at ``path``."""
    target = Path(path or DATABASE_PATH)
    if not target.exists():
        raise FileNotFoundError(f"No database at {target}")

    load_models()
    present = _database_schema(target)
    expected = Base.metadata.tables

    missing_tables = [name for name in expected if name not in present]
    missing_columns = [
        f"{name}.{column.name}"
        for name, table in expected.items()
        if name in present
        for column in table.columns
        if column.name not in present[name]
    ]
    unknown_tables = [name for name in present if name not in expected]

    return Drift(
        missing_tables=tuple(sorted(missing_tables)),
        missing_columns=tuple(sorted(missing_columns)),
        unknown_tables=tuple(sorted(unknown_tables)),
    )


def describe(drift: Drift) -> str:
    """A report meant to be read in a terminal by whoever just updated."""
    if drift.clean:
        report = ["Database schema matches the models."]
    else:
        report = []
        if drift.missing_tables:
            report.append(f"Missing tables ({len(drift.missing_tables)}):")
            report += [f"  {name}" for name in drift.missing_tables]
        if drift.missing_columns:
            report.append(f"Missing columns ({len(drift.missing_columns)}):")
            report += [f"  {name}" for name in drift.missing_columns]
        report.append("")
        if drift.healed_by_init_db:
            report.append("Starting Studio adds all of these. No action needed.")
        else:
            report.append(
                "Starting Studio will NOT add these columns: "
                + ", ".join(drift.unhealed_columns)
                + ". Name them in BACKFILLED_COLUMNS (vendoo_studio/database.py) "
                "before running against this database."
            )
    if drift.unknown_tables:
        report.append("")
        report.append(
            "Tables not in the models (left alone, listed for information): "
            + ", ".join(drift.unknown_tables)
        )
    return "\n".join(report)
