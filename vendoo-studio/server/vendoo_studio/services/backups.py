"""Consistent copies of the database, taken while Studio keeps running.

``VACUUM INTO`` writes a transactionally consistent copy that includes whatever
is still in the write-ahead log. Copying ``vendoo_studio.db`` as a file does
not: the ``-wal`` beside it keeps moving, so the pieces can come from different
instants and the copy opens short of its most recent writes. Every snapshot is
checked with ``PRAGMA integrity_check`` before it is kept, because a backup
nobody has opened is a guess rather than a backup.

Snapshots live beside the database in ``backups/`` and are gzipped: the
database is mostly JSON text and compresses around six-fold, which matters
because a month of them is kept and every one is copied to the backup folder
as well. When a backup folder is configured they go there too, which is the
copy that survives losing the machine.
"""

from __future__ import annotations

import gzip
import logging
import re
import shutil
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from pathlib import Path

from vendoo_studio.config import BACKUPS_DIR, DATABASE_PATH, PHOTOS_DIR
from vendoo_studio.services.user_settings import read_settings, update_settings

log = logging.getLogger("vendoo_studio.backups")

BACKUP_FOLDER_KEY = "backup_folder"
PREFIX = "vendoo_studio"
STAMP_FORMAT = "%Y%m%d-%H%M%S"
NAME_PATTERN = re.compile(rf"^{PREFIX}-(\d{{8}}-\d{{6}})-([a-z0-9-]+)\.db(\.gz)?$")

# Keep every snapshot from the last day, one per day for a month, and never
# drop the newest few whatever their age: an install that sat unused for a
# season should still have something to go back to.
KEEP_NEWEST = 3
KEEP_ALL_WITHIN = timedelta(days=1)
KEEP_DAILY_FOR = timedelta(days=30)

_lock = threading.Lock()


class BackupError(RuntimeError):
    """A snapshot could not be written, or could not be read back."""


@dataclass(frozen=True)
class Snapshot:
    path: Path
    taken_at: datetime
    reason: str
    size_bytes: int

    @property
    def compressed(self) -> bool:
        return self.path.suffix == ".gz"

    def as_dict(self) -> dict:
        return {
            "path": str(self.path),
            "name": self.path.name,
            "taken_at": self.taken_at.isoformat(),
            "reason": self.reason,
            "size_bytes": self.size_bytes,
            "compressed": self.compressed,
        }


def backups_dir() -> Path:
    path = Path(BACKUPS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def backup_folder() -> Path | None:
    """The off-machine destination, when one is configured."""
    raw = read_settings().get(BACKUP_FOLDER_KEY)
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Path(raw).expanduser()


def set_backup_folder(raw: object) -> Path | None:
    """Point snapshots at a folder, or pass None to stop copying them off."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        update_settings(lambda payload: payload.pop(BACKUP_FOLDER_KEY, None))
        return None
    if not isinstance(raw, str):
        raise ValueError("Backup folder must be a path")

    folder = Path(raw).expanduser()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".studio-write-test-{uuid.uuid4().hex}"
        probe.write_text("")
        probe.unlink()
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot write to {folder}: {exc}") from exc

    update_settings(lambda payload: payload.__setitem__(BACKUP_FOLDER_KEY, str(folder)))
    return folder


def _slug(reason: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", reason.lower()).strip("-")
    return cleaned or "manual"


def _parse(path: Path) -> Snapshot | None:
    match = NAME_PATTERN.match(path.name)
    if not match:
        return None
    try:
        taken_at = datetime.strptime(match.group(1), STAMP_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None
    return Snapshot(
        path=path,
        taken_at=taken_at,
        reason=match.group(2),
        size_bytes=path.stat().st_size,
    )


def _verify(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"{path.name} cannot be opened: {exc}") from exc
    finally:
        connection.close()
    if not result or result[0] != "ok":
        raise BackupError(f"{path.name} failed integrity_check: {result[0] if result else 'no result'}")


def list_snapshots(directory: Path | None = None) -> list[Snapshot]:
    """Every snapshot in the folder, newest first."""
    target = Path(directory) if directory else backups_dir()
    if not target.is_dir():
        return []
    found = [snapshot for path in target.glob(f"{PREFIX}-*") if (snapshot := _parse(path))]
    return sorted(found, key=lambda snapshot: snapshot.taken_at, reverse=True)


def latest_snapshot(directory: Path | None = None) -> Snapshot | None:
    snapshots = list_snapshots(directory)
    return snapshots[0] if snapshots else None


def _keepers(snapshots: list[Snapshot], now: datetime) -> set[Path]:
    keep = {snapshot.path for snapshot in snapshots[:KEEP_NEWEST]}
    seen_days: set[str] = set()
    for snapshot in snapshots:
        age = now - snapshot.taken_at
        if age <= KEEP_ALL_WITHIN:
            keep.add(snapshot.path)
            continue
        if age > KEEP_DAILY_FOR:
            continue
        day = snapshot.taken_at.strftime("%Y%m%d")
        if day not in seen_days:
            seen_days.add(day)
            keep.add(snapshot.path)
    return keep


def prune_snapshots(directory: Path | None = None, *, now: datetime | None = None) -> list[Path]:
    """Drop snapshots the retention rule no longer covers. Returns what went."""
    snapshots = list_snapshots(directory)
    keep = _keepers(snapshots, now or datetime.now(UTC))
    removed = []
    for snapshot in snapshots:
        if snapshot.path in keep:
            continue
        try:
            snapshot.path.unlink()
            removed.append(snapshot.path)
        except OSError as exc:
            log.warning("Could not remove %s: %s", snapshot.path, exc)
    return removed


def _mirror(snapshot: Snapshot) -> Path | None:
    folder = backup_folder()
    if folder is None:
        return None
    try:
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / snapshot.path.name
        shutil.copy2(snapshot.path, destination)
    except OSError as exc:
        # A missing external drive is not a reason to fail the snapshot that
        # already landed locally, but it does mean the off-machine copy is
        # stale, so say so loudly enough to find in the log.
        log.warning("Snapshot %s was not copied to %s: %s", snapshot.path.name, folder, exc)
        return None
    try:
        prune_snapshots(folder)
    except OSError as exc:
        log.warning("Could not prune %s: %s", folder, exc)
    return destination


def mirror_photos(folder: Path | None = None) -> int:
    """Copy photos that are not in the backup folder yet. Returns how many.

    Photo files are written once under a uuid name and never modified, so
    matching on name and size is enough to know a file is already there, and a
    plain copy can never catch one half-written the way a database can.

    Photos deleted in Studio are left in the backup folder on purpose: the
    point of a backup is to still have the thing you did not mean to delete.
    """
    destination_root = folder if folder is not None else backup_folder()
    if destination_root is None:
        return 0

    source_root = Path(PHOTOS_DIR)
    if not source_root.is_dir():
        return 0

    destination = destination_root / "photos"
    copied = 0
    try:
        destination.mkdir(parents=True, exist_ok=True)
        existing = {path.name: path.stat().st_size for path in destination.iterdir() if path.is_file()}
        for photo in sorted(source_root.iterdir()):
            if not photo.is_file() or photo.name.startswith("."):
                continue
            if existing.get(photo.name) == photo.stat().st_size:
                continue
            shutil.copy2(photo, destination / photo.name)
            copied += 1
    except OSError as exc:
        log.warning("Photos were not copied to %s: %s", destination, exc)
        return copied

    if copied:
        log.info("Copied %d photo(s) to %s", copied, destination)
    return copied


def decompress_snapshot(snapshot: Path, destination: Path) -> Path:
    """Write a plain SQLite file from a snapshot, compressed or not.

    Restores and schema checks need a real database file. Returns
    ``destination``, which is overwritten.
    """
    source = Path(snapshot)
    if source.suffix != ".gz":
        shutil.copy2(source, destination)
        return destination

    with gzip.open(source, "rb") as compressed, open(destination, "wb") as plain:
        shutil.copyfileobj(compressed, plain)
    return destination


def take_snapshot(reason: str, *, source: str | Path | None = None) -> Snapshot:
    """Write a verified copy of the database and return it.

    ``reason`` is recorded in the filename so it is obvious later which
    snapshot came from an update and which from a timer.
    """
    database = Path(source or DATABASE_PATH)
    if not database.exists():
        raise BackupError(f"No database at {database}")

    with _lock:
        directory = backups_dir()
        stamp = datetime.now(UTC).strftime(STAMP_FORMAT)
        final = directory / f"{PREFIX}-{stamp}-{_slug(reason)}.db.gz"
        staging = directory / f".{PREFIX}-{uuid.uuid4().hex}.tmp"
        staging.unlink(missing_ok=True)

        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            # VACUUM INTO refuses an existing target, hence the staging name.
            connection.execute("VACUUM INTO ?", (str(staging),))
        except sqlite3.DatabaseError as exc:
            staging.unlink(missing_ok=True)
            raise BackupError(f"Could not snapshot {database}: {exc}") from exc
        finally:
            connection.close()

        try:
            # Checked before compressing: gzip would happily wrap a corrupt
            # file, and the point is to know the copy opens.
            _verify(staging)
        except BackupError:
            staging.unlink(missing_ok=True)
            raise

        try:
            with open(staging, "rb") as plain, gzip.open(final, "wb", compresslevel=6) as compressed:
                shutil.copyfileobj(plain, compressed)
        except OSError as exc:
            final.unlink(missing_ok=True)
            raise BackupError(f"Could not compress {staging.name}: {exc}") from exc
        finally:
            staging.unlink(missing_ok=True)

        snapshot = _parse(final)
        if snapshot is None:  # pragma: no cover - the name is built above
            raise BackupError(f"Wrote an unreadable snapshot name: {final.name}")

    prune_snapshots(directory)
    _mirror(snapshot)
    # Photos are the part of the data that cannot be regenerated from anything
    # else, and they live outside the database, so they need their own copy.
    mirror_photos()
    log.info("Snapshot %s (%.1f MB)", snapshot.path.name, snapshot.size_bytes / 1_048_576)
    return snapshot


def snapshot_quietly(reason: str, *, source: str | Path | None = None) -> Snapshot | None:
    """Take a snapshot, logging rather than raising when it cannot be taken.

    For callers on a path that must continue regardless, like startup.
    """
    try:
        return take_snapshot(reason, source=source)
    except (BackupError, OSError) as exc:
        log.warning("No %s snapshot: %s", reason, exc)
        return None


SNAPSHOT_INTERVAL = timedelta(hours=6)

_timer_stop = threading.Event()
_timer: threading.Thread | None = None


def snapshot_is_due(*, now: datetime | None = None) -> bool:
    """True when the newest snapshot is older than the interval, or absent."""
    latest = latest_snapshot()
    if latest is None:
        return True
    return (now or datetime.now(UTC)) - latest.taken_at >= SNAPSHOT_INTERVAL


def start_snapshot_timer() -> threading.Thread | None:
    """Snapshot on startup when one is due, then keep snapshotting.

    Returns the thread, or None when one is already running. Failures are
    logged rather than raised: a backup that cannot be written must not stop
    Studio from opening.
    """
    global _timer

    if _timer is not None and _timer.is_alive():
        return None

    def _run() -> None:
        if snapshot_is_due():
            snapshot_quietly("startup")
        while not _timer_stop.wait(SNAPSHOT_INTERVAL.total_seconds()):
            snapshot_quietly("timer")

    _timer_stop.clear()
    _timer = threading.Thread(target=_run, name="studio-snapshots", daemon=True)
    _timer.start()
    return _timer


def stop_snapshot_timer(timeout: float = 5.0) -> None:
    """Ask the timer to finish. A snapshot already underway is allowed to end."""
    _timer_stop.set()
    if _timer is not None and _timer.is_alive():
        _timer.join(timeout=timeout)
