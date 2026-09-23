import os
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta, UTC
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from vendoo_studio.main import app

from vendoo_studio.services import backups
from vendoo_studio.services.backups import (
    BackupError,
    Snapshot,
    list_snapshots,
    prune_snapshots,
    set_backup_folder,
    snapshot_quietly,
    take_snapshot,
)


@pytest.fixture
def source_db(tmp_path):
    """A small database with a row that is still only in the write-ahead log."""
    path = tmp_path / "vendoo_studio.db"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE listings (id TEXT PRIMARY KEY, title TEXT)")
    connection.execute("INSERT INTO listings VALUES ('a', 'vintage jacket')")
    connection.commit()
    # Deliberately left open and un-checkpointed: this is the state the app is
    # in while running, and the state a plain file copy gets wrong.
    return path


@pytest.fixture
def backups_dir(tmp_path, monkeypatch):
    directory = tmp_path / "backups"
    monkeypatch.setattr(backups, "BACKUPS_DIR", str(directory))
    monkeypatch.setenv("VENDOO_STUDIO_DATA_DIR", str(tmp_path / "userdata"))
    return directory


def _rows(path):
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return connection.execute("SELECT id, title FROM listings").fetchall()
    finally:
        connection.close()


def test_snapshot_captures_uncheckpointed_writes(source_db, backups_dir):
    snapshot = take_snapshot("timer", source=source_db)

    assert snapshot.path.exists()
    assert _rows(snapshot.path) == [("a", "vintage jacket")]


def test_snapshot_records_its_reason_in_the_name(source_db, backups_dir):
    snapshot = take_snapshot("Pre Update", source=source_db)

    assert snapshot.reason == "pre-update"
    assert snapshot.path.name.endswith("-pre-update.db")
    assert snapshot.path.parent == backups_dir


def test_snapshot_does_not_freeze_later_writes(source_db, backups_dir):
    take_snapshot("first", source=source_db)
    connection = sqlite3.connect(source_db)
    connection.execute("INSERT INTO listings VALUES ('b', 'denim shirt')")
    connection.commit()
    connection.close()

    second = take_snapshot("second", source=source_db)

    assert len(_rows(second.path)) == 2


def test_corrupt_snapshot_is_discarded(source_db, backups_dir, monkeypatch):
    monkeypatch.setattr(
        backups, "_verify", lambda path: (_ for _ in ()).throw(BackupError("bad"))
    )

    with pytest.raises(BackupError):
        take_snapshot("timer", source=source_db)

    assert list_snapshots(backups_dir) == []
    assert list(backups_dir.glob("*")) == []


def test_missing_database_raises(tmp_path, backups_dir):
    with pytest.raises(BackupError):
        take_snapshot("timer", source=tmp_path / "absent.db")


def test_snapshot_quietly_swallows_failure(tmp_path, backups_dir, monkeypatch):
    monkeypatch.setattr(backups, "DATABASE_PATH", str(tmp_path / "absent.db"))

    assert snapshot_quietly("startup") is None


def test_snapshots_are_copied_to_the_backup_folder(source_db, backups_dir, tmp_path):
    external = tmp_path / "external drive" / "studio"
    set_backup_folder(str(external))

    snapshot = take_snapshot("timer", source=source_db)

    assert (external / snapshot.path.name).exists()
    assert _rows(external / snapshot.path.name) == [("a", "vintage jacket")]


def test_unwritable_backup_folder_is_rejected(backups_dir, tmp_path):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("")

    with pytest.raises(ValueError):
        set_backup_folder(str(blocker))


def test_clearing_the_backup_folder(backups_dir, tmp_path):
    set_backup_folder(str(tmp_path / "external"))
    assert backups.backup_folder() is not None

    assert set_backup_folder(None) is None
    assert backups.backup_folder() is None


def test_unreachable_backup_folder_keeps_the_local_snapshot(source_db, backups_dir, tmp_path, monkeypatch):
    """An unplugged drive must not cost you the snapshot that did land."""
    set_backup_folder(str(tmp_path / "external"))
    not_a_directory = tmp_path / "drive-file"
    not_a_directory.write_text("")
    monkeypatch.setattr(backups, "backup_folder", lambda: not_a_directory / "studio")

    snapshot = take_snapshot("timer", source=source_db)

    assert snapshot.path.exists()
    assert _rows(snapshot.path) == [("a", "vintage jacket")]


def _stub(directory, days_ago, reason="timer", now=None):
    taken = (now or datetime.now(UTC)) - timedelta(days=days_ago)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"vendoo_studio-{taken.strftime('%Y%m%d-%H%M%S')}-{reason}.db"
    path.write_text("")
    return Snapshot(path=path, taken_at=taken, reason=reason, size_bytes=0)


def test_prune_keeps_newest_and_one_per_day(backups_dir):
    now = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    # Spread same-day snapshots across hours so "newest three" is unambiguous.
    today = [
        _stub(backups_dir, hour / 24, f"run{n}", now)
        for n, hour in enumerate([0, 1, 2, 3])
    ]
    # Both of these land on 2026-09-17; only the newer one should survive.
    _stub(backups_dir, 3, "morning", now)
    _stub(backups_dir, 3.1, "evening", now)
    ancient = _stub(backups_dir, 400, "old", now)

    prune_snapshots(backups_dir, now=now)

    kept = {snapshot.path.name for snapshot in list_snapshots(backups_dir)}
    assert {snapshot.path.name for snapshot in today[:3]} <= kept
    assert today[3].path.name not in kept
    assert len([name for name in kept if "morning" in name or "evening" in name]) == 1
    assert ancient.path.name not in kept


def test_prune_caps_how_many_snapshots_are_kept(backups_dir, monkeypatch):
    monkeypatch.setattr(backups, "MAX_SNAPSHOT_COUNT", 5)
    now = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    for days in range(10):
        _stub(backups_dir, days, f"day{days}", now)

    prune_snapshots(backups_dir, now=now)

    assert len(list_snapshots(backups_dir)) == 5


def test_prune_caps_how_much_disk_snapshots_are_worth(backups_dir, monkeypatch):
    """A month of daily copies of a multi-GB database is not a month worth keeping."""
    monkeypatch.setattr(backups, "MAX_RETAINED_BYTES", 10_000)
    now = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    for days in range(8):
        path = _stub(backups_dir, days, f"day{days}", now).path
        path.write_bytes(b"x" * 4_000)

    prune_snapshots(backups_dir, now=now)

    # The newest three are kept whatever the cap says; nothing older survives it.
    assert len(list_snapshots(backups_dir)) == 3


def test_a_snapshot_is_refused_when_the_disk_is_nearly_full(source_db, backups_dir, monkeypatch):
    monkeypatch.setattr(
        backups.shutil,
        "disk_usage",
        lambda path: type("Usage", (), {"total": 0, "used": 0, "free": 8})(),
    )

    with pytest.raises(BackupError, match="free disk space"):
        take_snapshot("timer", source=source_db)

    assert list_snapshots(backups_dir) == []


def test_storage_status_reports_the_low_disk_warning(source_db, backups_dir, monkeypatch):
    monkeypatch.setattr(
        backups.shutil,
        "disk_usage",
        lambda path: type("Usage", (), {"total": 0, "used": 0, "free": 8})(),
    )

    status = backups.storage_status(source=source_db)

    assert status["can_snapshot"] is False
    assert "free disk space" in status["warning"]
    assert status["database_bytes"] > 0


def test_prune_never_empties_an_old_install(backups_dir):
    now = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    for days in (400, 401, 402, 403):
        _stub(backups_dir, days, f"old{days}", now)

    prune_snapshots(backups_dir, now=now)

    assert len(list_snapshots(backups_dir)) == 3


def test_snapshot_is_due_when_none_exist(backups_dir):
    assert backups.snapshot_is_due()


def test_snapshot_is_not_due_right_after_one(source_db, backups_dir):
    take_snapshot("timer", source=source_db)

    assert not backups.snapshot_is_due()


def test_snapshot_is_due_once_the_interval_passes(source_db, backups_dir):
    take_snapshot("timer", source=source_db)
    later = datetime.now(UTC) + backups.SNAPSHOT_INTERVAL + timedelta(minutes=1)

    assert backups.snapshot_is_due(now=later)


def test_timer_snapshots_on_start_and_stops_cleanly(source_db, backups_dir, monkeypatch):
    monkeypatch.setattr(backups, "DATABASE_PATH", str(source_db))
    monkeypatch.setattr(backups, "SNAPSHOT_INTERVAL", timedelta(seconds=30))

    thread = backups.start_snapshot_timer()
    assert thread is not None
    for _ in range(50):
        if list_snapshots(backups_dir):
            break
        time.sleep(0.02)
    backups.stop_snapshot_timer(timeout=2)

    assert not thread.is_alive()
    assert [snapshot.reason for snapshot in list_snapshots(backups_dir)] == ["startup"]


def test_timer_is_not_started_twice(source_db, backups_dir, monkeypatch):
    monkeypatch.setattr(backups, "DATABASE_PATH", str(source_db))
    try:
        first = backups.start_snapshot_timer()
        second = backups.start_snapshot_timer()

        assert first is not None
        assert second is None
    finally:
        backups.stop_snapshot_timer(timeout=2)


class BackupRoutesTest(unittest.TestCase):
    """The API the app and the brother's install talk to."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._previous = os.environ.get("VENDOO_STUDIO_DATA_DIR")
        os.environ["VENDOO_STUDIO_DATA_DIR"] = str(root)
        self.backups_dir = root / "backups"
        self.database = root / "vendoo_studio.db"
        connection = sqlite3.connect(self.database)
        connection.execute("CREATE TABLE listings (id TEXT PRIMARY KEY)")
        connection.commit()
        connection.close()
        self._patches = [
            patch.object(backups, "BACKUPS_DIR", str(self.backups_dir)),
            patch.object(backups, "DATABASE_PATH", str(self.database)),
        ]
        for item in self._patches:
            item.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        for item in self._patches:
            item.stop()
        self.tmp.cleanup()
        if self._previous is None:
            os.environ.pop("VENDOO_STUDIO_DATA_DIR", None)
        else:
            os.environ["VENDOO_STUDIO_DATA_DIR"] = self._previous

    def test_listing_is_empty_before_any_snapshot(self):
        body = self.client.get("/api/backups").json()

        self.assertEqual(body["snapshots"], [])
        self.assertIsNone(body["latest"])
        self.assertIsNone(body["folder"])

    def test_creating_and_then_listing_a_snapshot(self):
        created = self.client.post("/api/backups")
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["snapshot"]["reason"], "manual")

        body = self.client.get("/api/backups").json()
        self.assertEqual(len(body["snapshots"]), 1)
        self.assertEqual(body["latest"]["reason"], "manual")

    def test_setting_and_clearing_the_backup_folder(self):
        external = Path(self.tmp.name) / "external"

        response = self.client.put("/api/backups/folder", json={"folder": str(external)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["folder"], str(external))

        cleared = self.client.put("/api/backups/folder", json={"folder": None})
        self.assertIsNone(cleared.json()["folder"])

    def test_an_unusable_backup_folder_is_a_400(self):
        blocker = Path(self.tmp.name) / "file"
        blocker.write_text("")

        response = self.client.put("/api/backups/folder", json={"folder": str(blocker / "sub")})

        self.assertEqual(response.status_code, 400)

    def test_a_failed_snapshot_is_a_500(self):
        self.database.unlink()

        response = self.client.post("/api/backups")

        self.assertEqual(response.status_code, 500)


@pytest.fixture
def photos(tmp_path, monkeypatch):
    directory = tmp_path / "photos"
    directory.mkdir()
    monkeypatch.setattr(backups, "PHOTOS_DIR", str(directory))
    return directory


def test_photos_are_copied_to_the_backup_folder(source_db, backups_dir, photos, tmp_path):
    (photos / "abc123.jpg").write_bytes(b"jacket-front")
    (photos / "def456.jpg").write_bytes(b"jacket-back")
    external = tmp_path / "external"
    set_backup_folder(str(external))

    take_snapshot("timer", source=source_db)

    assert (external / "photos" / "abc123.jpg").read_bytes() == b"jacket-front"
    assert (external / "photos" / "def456.jpg").read_bytes() == b"jacket-back"


def test_photos_already_copied_are_not_copied_again(backups_dir, photos, tmp_path):
    (photos / "abc123.jpg").write_bytes(b"jacket-front")
    external = tmp_path / "external"

    assert backups.mirror_photos(external) == 1
    assert backups.mirror_photos(external) == 0


def test_a_changed_photo_is_copied_again(backups_dir, photos, tmp_path):
    (photos / "abc123.jpg").write_bytes(b"short")
    external = tmp_path / "external"
    backups.mirror_photos(external)

    (photos / "abc123.jpg").write_bytes(b"a longer replacement")

    assert backups.mirror_photos(external) == 1
    assert (external / "photos" / "abc123.jpg").read_bytes() == b"a longer replacement"


def test_photos_deleted_in_studio_stay_in_the_backup(backups_dir, photos, tmp_path):
    """Deleting a listing must not reach back and delete the backup copy."""
    (photos / "abc123.jpg").write_bytes(b"jacket-front")
    external = tmp_path / "external"
    backups.mirror_photos(external)

    (photos / "abc123.jpg").unlink()
    backups.mirror_photos(external)

    assert (external / "photos" / "abc123.jpg").exists()


def test_no_backup_folder_means_no_photo_copying(backups_dir, photos):
    (photos / "abc123.jpg").write_bytes(b"jacket-front")

    assert backups.mirror_photos() == 0


def test_an_unreachable_photo_destination_is_survivable(source_db, backups_dir, photos, tmp_path):
    (photos / "abc123.jpg").write_bytes(b"jacket-front")
    blocker = tmp_path / "drive-file"
    blocker.write_text("")

    assert backups.mirror_photos(blocker / "studio") == 0
