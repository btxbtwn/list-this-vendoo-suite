import sqlite3

import pytest

from vendoo_studio.services.schema_drift import describe, inspect_database


@pytest.fixture
def database(tmp_path, monkeypatch):
    """A database built from the current models, at a throwaway path."""
    path = tmp_path / "studio.db"
    monkeypatch.setenv("VENDOO_STUDIO_DATA_DIR", str(tmp_path))
    from sqlalchemy import create_engine

    from vendoo_studio.database import Base, load_models

    load_models()
    Base.metadata.create_all(bind=create_engine(f"sqlite:///{path}"))
    return path


def test_current_schema_is_clean(database):
    drift = inspect_database(database)
    assert drift.clean
    assert "matches the models" in describe(drift)


def test_missing_table_is_reported_and_heals(database):
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE fill_log_entries")

    drift = inspect_database(database)
    assert "fill_log_entries" in drift.missing_tables
    assert not drift.clean
    assert drift.healed_by_init_db
    assert "No action needed" in describe(drift)


def test_missing_column_is_reported_as_unhealed(database):
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE conversations DROP COLUMN notes")

    drift = inspect_database(database)
    assert "conversations.notes" in drift.missing_columns
    assert not drift.healed_by_init_db
    assert "will NOT add these columns" in describe(drift)


def test_backfilled_column_is_reported_as_healing(database):
    """settled_at is named in BACKFILLED_COLUMNS, so startup restores it."""
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE conversations DROP COLUMN settled_at")

    drift = inspect_database(database)
    assert "conversations.settled_at" in drift.missing_columns
    assert drift.healed_by_init_db
    assert "No action needed" in describe(drift)


def test_unknown_table_is_listed_but_not_a_failure(database):
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE leftovers (id TEXT PRIMARY KEY)")

    drift = inspect_database(database)
    assert drift.clean
    assert "leftovers" in drift.unknown_tables
    assert "leftovers" in describe(drift)


def test_missing_database_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        inspect_database(tmp_path / "absent.db")
