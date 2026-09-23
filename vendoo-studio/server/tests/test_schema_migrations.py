import sqlite3

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import OperationalError

from vendoo_studio.services import backups, schema_migrations
from vendoo_studio.services.schema_drift import inspect_database
from vendoo_studio.services.schema_migrations import (
    SchemaError,
    ensure_schema,
    head_revision,
    recorded_revision,
)


@pytest.fixture
def snapshots(tmp_path, monkeypatch):
    directory = tmp_path / "backups"
    monkeypatch.setattr(backups, "BACKUPS_DIR", str(directory))
    monkeypatch.setenv("VENDOO_STUDIO_DATA_DIR", str(tmp_path / "userdata"))
    return directory


@pytest.fixture
def engine(tmp_path):
    return create_engine(f"sqlite:///{tmp_path / 'studio.db'}")


def _legacy_database(engine):
    """A database as an older build left it: real tables, never stamped."""
    from vendoo_studio.database import Base, load_models

    load_models()
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        from sqlalchemy import text

        connection.execute(
            text("INSERT INTO conversations (id, title) VALUES ('keep-me', 'vintage coat')")
        )
    return engine


def test_head_revision_is_resolvable():
    assert head_revision()
    assert schema_migrations.migrations_dir().is_dir()


def test_fresh_database_is_created_at_head(engine, snapshots):
    revision = ensure_schema(engine)

    assert revision == head_revision()
    assert recorded_revision(engine) == head_revision()
    assert inspect_database(engine.url.database).clean


def test_fresh_database_is_not_snapshotted(engine, snapshots):
    """There is nothing to lose yet, so do not litter the backups folder."""
    ensure_schema(engine)

    assert backups.list_snapshots(snapshots) == []


def test_legacy_database_is_adopted_without_losing_rows(engine, snapshots):
    _legacy_database(engine)
    assert recorded_revision(engine) is None

    revision = ensure_schema(engine)

    assert revision == head_revision()
    assert recorded_revision(engine) == head_revision()
    with sqlite3.connect(engine.url.database) as connection:
        rows = connection.execute("SELECT title FROM conversations").fetchall()
    assert rows == [("vintage coat",)]


def test_adopting_a_legacy_database_snapshots_first(engine, snapshots):
    _legacy_database(engine)

    ensure_schema(engine)

    assert [snapshot.reason for snapshot in backups.list_snapshots(snapshots)] == ["pre-adopt"]


def test_legacy_database_missing_a_column_is_repaired(engine, snapshots):
    """The gap an older build left behind is closed before the stamp goes on."""
    _legacy_database(engine)
    with sqlite3.connect(engine.url.database) as connection:
        connection.execute("ALTER TABLE conversations DROP COLUMN settled_at")

    ensure_schema(engine)

    assert "settled_at" in {
        column["name"] for column in inspect(engine).get_columns("conversations")
    }


def test_unrepairable_legacy_database_refuses_the_stamp(engine, snapshots, monkeypatch):
    """A gap that survives healing must not be stamped as current."""
    _legacy_database(engine)
    from vendoo_studio.services.schema_drift import Drift

    monkeypatch.setattr(
        "vendoo_studio.services.schema_drift.inspect_database",
        lambda path=None: Drift(
            missing_tables=(),
            missing_columns=("listings.price",),
            unknown_tables=(),
        ),
    )

    with pytest.raises(SchemaError, match="listings.price"):
        ensure_schema(engine)

    assert recorded_revision(engine) is None


def test_a_database_from_a_newer_build_is_refused(engine, snapshots):
    ensure_schema(engine)
    with sqlite3.connect(engine.url.database) as connection:
        connection.execute("UPDATE alembic_version SET version_num = 'f00dcafe9999'")

    with pytest.raises(SchemaError, match="newer version"):
        ensure_schema(engine)


def test_an_up_to_date_database_is_left_alone(engine, snapshots):
    ensure_schema(engine)
    before = backups.list_snapshots(snapshots)

    assert ensure_schema(engine) == head_revision()
    assert backups.list_snapshots(snapshots) == before


def test_ensure_schema_is_idempotent(engine, snapshots):
    first = ensure_schema(engine)
    second = ensure_schema(engine)
    third = ensure_schema(engine)

    assert first == second == third
    assert inspect_database(engine.url.database).clean


def test_the_draft_cache_takes_over_from_the_old_draft_events(engine, snapshots):
    """A database from the previous release keeps its statuses and loses the bulk."""
    from alembic import command

    config = schema_migrations.alembic_config(str(engine.url))
    command.upgrade(config, "c3a71f0b5d42")
    with sqlite3.connect(engine.url.database) as connection:
        connection.execute(
            "INSERT INTO conversations (id, title) VALUES ('c1', 'vintage coat')"
        )
        connection.execute(
            "INSERT INTO jobs (id, conversation_id, approved_revision_id, listing_snapshot) "
            "VALUES ('j1', 'c1', 'r1', '{}')"
        )
        for sequence, listed in enumerate([False, False, True]):
            payload = (
                '{"ok": true, "source": "vendoo_sync", "item_id": "itm1", '
                '"url": "https://web.vendoo.co/app/item/itm1", '
                '"item": {"generalDetails": {"description": "' + "x" * 2000 + '"}, '
                '"listings": {"ebay": {"status": {"listed": ' + str(listed).lower() + '}}}}}'
            )
            connection.execute(
                "INSERT INTO job_events (id, job_id, sequence, event_type, payload, created_at) "
                f"VALUES ('e{sequence}', 'j1', {sequence}, 'vendoo_draft', ?, "
                f"'2026-09-2{sequence} 00:00:00')",
                (payload,),
            )

    assert ensure_schema(engine) == head_revision()

    with sqlite3.connect(engine.url.database) as connection:
        cached = connection.execute(
            "SELECT item_id, source, payload FROM vendoo_draft_cache"
        ).fetchall()
        left = connection.execute(
            "SELECT COUNT(*) FROM job_events WHERE event_type = 'vendoo_draft'"
        ).fetchone()

    assert left == (0,)
    assert len(cached) == 1
    item_id, source, payload = cached[0]
    assert (item_id, source) == ("itm1", "vendoo_sync")
    assert payload == '{"item": {"listings": {"ebay": {"status": {"listed": true}}}}}'


REVISION_TEMPLATE = '''"""{message}"""
from alembic import op
import sqlalchemy as sa

revision = {revision!r}
down_revision = {down!r}
branch_labels = None
depends_on = None


def upgrade() -> None:
    {upgrade}


def downgrade() -> None:
    pass
'''


@pytest.fixture
def scripted_migrations(tmp_path, monkeypatch):
    """A migrations folder this test owns, so revisions can be added to it."""
    directory = tmp_path / "migrations"
    (directory / "versions").mkdir(parents=True)
    real = schema_migrations.migrations_dir()
    (directory / "env.py").write_text((real / "env.py").read_text())
    (directory / "script.py.mako").write_text((real / "script.py.mako").read_text())
    monkeypatch.setattr(schema_migrations, "migrations_dir", lambda: directory)

    def add(revision, down, upgrade, message="test revision"):
        (directory / "versions" / f"{revision}.py").write_text(
            REVISION_TEMPLATE.format(
                message=message, revision=revision, down=down, upgrade=upgrade
            )
        )

    return add


def test_a_new_revision_is_applied_and_snapshotted_first(engine, snapshots, scripted_migrations):
    scripted_migrations(
        "0001",
        None,
        "op.create_table('probe', sa.Column('id', sa.String(), primary_key=True))",
    )
    assert ensure_schema(engine) == "0001"
    assert backups.list_snapshots(snapshots) == []

    scripted_migrations(
        "0002",
        "0001",
        "op.add_column('probe', sa.Column('note', sa.String(), nullable=True))",
    )

    assert ensure_schema(engine) == "0002"
    assert "note" in {column["name"] for column in inspect(engine).get_columns("probe")}
    assert [snapshot.reason for snapshot in backups.list_snapshots(snapshots)] == ["pre-migration"]


def test_a_failing_revision_leaves_the_snapshot_behind(engine, snapshots, scripted_migrations):
    """When a migration blows up, the copy taken beforehand is what saves you."""
    scripted_migrations(
        "0001",
        None,
        "op.create_table('probe', sa.Column('id', sa.String(), primary_key=True))",
    )
    ensure_schema(engine)

    scripted_migrations("0002", "0001", "op.drop_table('does_not_exist')")

    with pytest.raises(OperationalError):
        ensure_schema(engine)

    snapshot = backups.latest_snapshot(snapshots)
    assert snapshot is not None
    assert snapshot.reason == "pre-migration"
    restored = sqlite3.connect(f"file:{snapshot.path}?mode=ro", uri=True)
    try:
        assert restored.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("0001",)
    finally:
        restored.close()


def test_the_models_match_the_migrations(engine, snapshots):
    """A model change without a revision must fail here, not on someone's machine.

    Everything the migrations build is compared against what the models
    declare. A column added to a model and not to a revision shows up as a
    difference, which is the failure earlier builds could not detect: startup
    would create nothing, and the gap would surface later as a query error on
    a database that had already been through an update.
    """
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    from vendoo_studio.database import Base, load_models

    load_models()
    ensure_schema(engine)

    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences == [], (
        "The models and the migrations have drifted apart. Generate a revision:\n"
        "  cd vendoo-studio && .venv/bin/alembic revision --autogenerate -m \"...\"\n"
        f"Differences: {differences}"
    )
