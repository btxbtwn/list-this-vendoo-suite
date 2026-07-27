from __future__ import annotations

import contextlib
import os
import shutil
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Iterator, Literal

from PIL import Image

from .config import Settings
from .images import MAX_STROKES_PER_JOB, MaskStroke


class StoreError(RuntimeError):
    pass


class JobNotFound(StoreError):
    pass


class JobPending(StoreError):
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        super().__init__("Job is still being created.")


class JobTerminal(StoreError):
    def __init__(self, job_id: str, state: str) -> None:
        self.job_id = job_id
        self.state = state
        super().__init__(f"Job is {state}.")


class StoreCapacityError(StoreError):
    pass


class StrokeLimitError(StoreError):
    pass


class StoreDeletionError(StoreError):
    pass


class StoreCreationError(StoreError):
    """Lightweight create failure with no image-bearing traceback chain."""

    def __init__(self, classification: str, message: str) -> None:
        self.classification = classification
        super().__init__(message)


def normalize_job_id(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError("Job id must be a UUID or 32 hexadecimal characters.") from exc
    normalized = parsed.hex
    if value.lower().replace("-", "") != normalized or len(value) not in (32, 36):
        raise ValueError("Job id must be a canonical UUID or 32 hexadecimal characters.")
    return normalized


@dataclass
class Job:
    id: str
    directory: Path
    width: int
    height: int
    created_at: float
    last_access: float
    disk_bytes: int
    generation: str
    strokes: list[MaskStroke] = field(default_factory=list)
    revision: int = 0
    lock: threading.RLock = field(default_factory=threading.RLock)

    @property
    def original_path(self) -> Path:
        return self.directory / "original.png"

    @property
    def mask_path(self) -> Path:
        return self.directory / "mask.png"


@dataclass
class JobLifecycle:
    state: Literal["creating", "live", "failed", "tombstoned"]
    updated_at: float
    job: Job | None = None
    error: str | None = None
    generation: str | None = None

    # Compatibility-only views. Cleanup storage is deliberately not lifecycle state.
    @property
    def directory(self) -> Path | None:
        return self.job.directory if self.job is not None else None

    @property
    def disk_bytes(self) -> int:
        return self.job.disk_bytes if self.job is not None else 0


@dataclass(frozen=True)
class JobSnapshot:
    id: str
    directory: Path
    width: int
    height: int
    created_at: float
    last_access: float
    disk_bytes: int
    generation: str
    revision: int


@dataclass(frozen=True)
class LifecycleSnapshot:
    state: Literal["creating", "live", "failed", "tombstoned"]
    updated_at: float
    job: JobSnapshot | None = None
    error: str | None = None
    generation: str | None = None

    @property
    def directory(self) -> Path | None:
        return self.job.directory if self.job is not None else None

    @property
    def disk_bytes(self) -> int:
        return self.job.disk_bytes if self.job is not None else 0


@dataclass(frozen=True)
class Quarantine:
    id: str
    job_id: str
    generation: str
    directory: Path
    disk_bytes: int
    error: str


@dataclass
class GenerationLease:
    job_id: str
    generation: str
    started_at: float
    active: bool = True
    cancelled: bool = False
    reserved_disk_bytes: int = 0
    reserved_memory_bytes: int = 0
    directory: Path | None = None
    storage_transferred_to_quarantine: bool = False


@dataclass
class BodyLease:
    id: str
    reserved_bytes: int = 0
    spool_memory_bytes: int = 0
    spool_disk_bytes: int = 0


@dataclass(frozen=True)
class RenderLease:
    id: str
    reserved_memory_bytes: int


class _MeteredWriter:
    def __init__(self, handle: BinaryIO, limit: int) -> None:
        self._handle = handle
        self._limit = limit
        self._written = 0

    def write(self, data: bytes) -> int:
        if self._written + len(data) > self._limit:
            raise StoreCapacityError("Encoded job storage exceeded its conservative reservation.")
        written = self._handle.write(data)
        self._written += written
        return written

    def __getattr__(self, name: str):
        return getattr(self._handle, name)


class JobStore:
    WAIT_SECONDS = 5.0

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.temp_root
        self._jobs: dict[str, Job] = {}
        self._lifecycles: dict[str, JobLifecycle] = {}
        self._generation_leases: dict[str, GenerationLease] = {}
        self._body_leases: dict[str, BodyLease] = {}
        self._render_leases: dict[str, RenderLease] = {}
        self._quarantines: dict[str, Quarantine] = {}
        self._terminal_registry_max = settings.terminal_registry_max or max(16, settings.max_jobs * 16)
        self._used_job_ids: set[str] = set()
        self._disk_bytes = 0
        self._reserved_disk_bytes = 0
        self._reserved_memory_bytes = 0
        self._body_bytes = 0
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._lock_file = None
        self._closing = False

    def startup(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        if self.settings.process_lock:
            import fcntl
            lock_path = self.root / ".process.lock"
            descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            os.chmod(lock_path, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                os.close(descriptor)
                raise RuntimeError("Another Background Studio backend is using this temporary root.") from exc
            self._lock_file = descriptor
        try:
            for path in self.root.glob("job-*"):
                if path.is_dir():
                    try:
                        shutil.rmtree(path)
                    except OSError as exc:
                        raise StoreDeletionError(
                            f"Could not remove stale temporary job directory {path.name}; startup is blocked."
                        ) from exc
        except BaseException:
            self._release_process_lock()
            raise
        with self._changed:
            self._closing = False
            self._changed.notify_all()

    def _release_process_lock(self) -> None:
        if self._lock_file is None:
            return
        import fcntl
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_UN)
        finally:
            os.close(self._lock_file)
            self._lock_file = None

    def _forget_terminal_locked(self, now: float) -> None:
        cutoff = now - self.settings.job_ttl_seconds
        for job_id, lifecycle in list(self._lifecycles.items()):
            if lifecycle.state in ("failed", "tombstoned") and lifecycle.updated_at <= cutoff:
                # Exact IDs remain recorded while detailed errors expire.
                self._lifecycles.pop(job_id, None)

    @staticmethod
    def _job_snapshot(job: Job | None) -> JobSnapshot | None:
        if job is None:
            return None
        return JobSnapshot(
            job.id, job.directory, job.width, job.height, job.created_at,
            job.last_access, job.disk_bytes, job.generation, job.revision,
        )

    @classmethod
    def _snapshot(cls, lifecycle: JobLifecycle) -> LifecycleSnapshot:
        return LifecycleSnapshot(
            lifecycle.state, lifecycle.updated_at, cls._job_snapshot(lifecycle.job),
            lifecycle.error, lifecycle.generation,
        )

    def _occupied_slots_locked(self) -> int:
        occupied = {job_id for job_id, state in self._lifecycles.items() if state.state == "live"}
        occupied.update(lease.job_id for lease in self._generation_leases.values() if lease.active)
        return len(occupied)

    def reserve_body(self, requested_bytes: int = 0) -> BodyLease:
        lease = BodyLease(uuid.uuid4().hex)
        with self._changed:
            if self._closing:
                raise StoreCapacityError("The backend is shutting down and is not accepting new work.")
            self._resize_body_locked(lease, requested_bytes)
            self._body_leases[lease.id] = lease
        return lease

    def _resize_body_locked(self, lease: BodyLease, requested_bytes: int) -> None:
        requested_bytes = max(0, requested_bytes)
        delta = requested_bytes - lease.reserved_bytes
        if delta > 0 and (
            self._body_bytes + delta > self.settings.inflight_body_quota_bytes
            or self._body_bytes + self._reserved_memory_bytes + delta > self.settings.memory_quota_bytes
        ):
            raise StoreCapacityError("The in-flight request body limit has been reached. Try again later.")
        self._body_bytes += delta
        lease.reserved_bytes = requested_bytes

    def resize_body(self, lease_id: str, requested_bytes: int) -> None:
        with self._changed:
            lease = self._body_leases.get(lease_id)
            if lease is None:
                raise StoreCapacityError("The request body reservation is no longer active.")
            self._resize_body_locked(lease, requested_bytes)

    def release_body(self, lease_id: str) -> None:
        with self._changed:
            lease = self._body_leases.pop(lease_id, None)
            if lease is not None:
                self._body_bytes -= lease.reserved_bytes + lease.spool_memory_bytes
                self._reserved_disk_bytes -= lease.spool_disk_bytes
                lease.reserved_bytes = 0
                lease.spool_memory_bytes = 0
                lease.spool_disk_bytes = 0
                self._changed.notify_all()

    def reserve_parser_spool(self, lease_id: str, body_bytes: int, memory_threshold: int) -> None:
        """Charge the multipart parser's independent copy alongside the raw body."""
        body_bytes = max(0, body_bytes)
        # Many individually sub-threshold multipart parts can coexist in RAM.
        memory_bytes = body_bytes
        disk_bytes = body_bytes
        with self._changed:
            lease = self._body_leases.get(lease_id)
            if lease is None:
                raise StoreCapacityError("The request body reservation is no longer active.")
            memory_delta = memory_bytes - lease.spool_memory_bytes
            disk_delta = disk_bytes - lease.spool_disk_bytes
            if self._body_bytes + self._reserved_memory_bytes + memory_delta > self.settings.memory_quota_bytes:
                raise StoreCapacityError("The in-flight multipart parser memory limit has been reached. Try again later.")
            if self._disk_bytes + self._reserved_disk_bytes + disk_delta > self.settings.disk_quota_bytes:
                raise StoreCapacityError("The temporary disk quota has been reached. Delete a job and try again.")
            self._body_bytes += memory_delta
            self._reserved_disk_bytes += disk_delta
            lease.spool_memory_bytes = memory_bytes
            lease.spool_disk_bytes = disk_bytes

    def reserve_render(self, job_id: str, operation: Literal["original", "preview", "export"]) -> RenderLease:
        """Reserve a conservative transient decode/render/encode working set."""
        job_id = normalize_job_id(job_id)
        with self._changed:
            lifecycle = self._lifecycles.get(job_id)
            job = self._jobs.get(job_id)
            if lifecycle is None or lifecycle.state != "live" or lifecycle.job is not job or job is None:
                if lifecycle is not None and lifecycle.state == "creating":
                    raise JobPending(job_id)
                if lifecycle is not None and lifecycle.state in ("failed", "tombstoned"):
                    raise JobTerminal(job_id, lifecycle.state)
                raise JobNotFound(job_id)
            pixels = job.width * job.height
            if operation == "original":
                memory_bytes = pixels * 6 + self._png_bound(job.width, job.height, 3)
            elif operation == "preview":
                scale = min(1.0, self.settings.preview_max_side / max(job.width, job.height))
                width = max(1, round(job.width * scale))
                height = max(1, round(job.height * scale))
                preview_pixels = width * height
                memory_bytes = pixels * 4 + preview_pixels * 9 + self._png_bound(width, height, 4)
            else:
                memory_bytes = pixels * 9 + self._png_bound(job.width, job.height, 4)
            if self._body_bytes + self._reserved_memory_bytes + memory_bytes > self.settings.memory_quota_bytes:
                raise StoreCapacityError("The response render memory limit has been reached. Try again later.")
            lease = RenderLease(uuid.uuid4().hex, memory_bytes)
            self._render_leases[lease.id] = lease
            self._reserved_memory_bytes += memory_bytes
            return lease

    def release_render(self, lease_id: str) -> None:
        with self._changed:
            lease = self._render_leases.pop(lease_id, None)
            if lease is not None:
                self._reserved_memory_bytes -= lease.reserved_memory_bytes
                self._changed.notify_all()

    def reserve(self, job_id: str | None = None, wait_seconds: float | None = None) -> tuple[str, bool, LifecycleSnapshot, str | None]:
        normalized = normalize_job_id(job_id) if job_id is not None else uuid.uuid4().hex
        deadline = time.monotonic() + (self.WAIT_SECONDS if wait_seconds is None else max(0.0, wait_seconds))
        with self._changed:
            if self._closing:
                raise StoreCapacityError("The backend is shutting down and is not accepting new work.")
            if job_id is None:
                attempts = 0
                while normalized in self._used_job_ids and attempts < 64:
                    normalized = uuid.uuid4().hex
                    attempts += 1
                if normalized in self._used_job_ids:
                    raise StoreCapacityError("The public job-id space is unavailable. Restart the backend and try again.")
            self._forget_terminal_locked(time.monotonic())
            lifecycle = self._lifecycles.get(normalized)
            if lifecycle is None:
                if normalized in self._used_job_ids:
                    lifecycle = JobLifecycle("tombstoned", time.monotonic())
                    return normalized, False, self._snapshot(lifecycle), None
                if len(self._used_job_ids) >= self._terminal_registry_max:
                    raise StoreCapacityError("The terminal job-id registry is full. Restart the backend and try again.")
                if self._occupied_slots_locked() >= self.settings.max_jobs:
                    raise StoreCapacityError("The job limit has been reached. Delete a job and try again.")
                lifecycle = JobLifecycle("creating", time.monotonic(), generation=uuid.uuid4().hex)
                self._lifecycles[normalized] = lifecycle
                self._used_job_ids.add(normalized)
                self._generation_leases[lifecycle.generation] = GenerationLease(
                    normalized, lifecycle.generation, lifecycle.updated_at
                )
                return normalized, True, self._snapshot(lifecycle), lifecycle.generation
            while lifecycle.state == "creating":
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return normalized, False, self._snapshot(lifecycle), None
                self._changed.wait(remaining)
            if lifecycle.state == "live" and lifecycle.job is not None:
                lifecycle.job.last_access = time.monotonic()
            return normalized, False, self._snapshot(lifecycle), None

    def lifecycle(self, job_id: str) -> LifecycleSnapshot | None:
        try:
            job_id = normalize_job_id(job_id)
        except ValueError:
            return None
        with self._lock:
            self._forget_terminal_locked(time.monotonic())
            lifecycle = self._lifecycles.get(job_id)
            if lifecycle and lifecycle.state == "live" and lifecycle.job:
                lifecycle.job.last_access = time.monotonic()
            if lifecycle is None and job_id in self._used_job_ids:
                return LifecycleSnapshot("tombstoned", time.monotonic())
            return self._snapshot(lifecycle) if lifecycle is not None else None

    def reserve_upload_copy(self, job_id: str, generation: str, upload_bytes: int) -> int:
        """Atomically charge a generation copy without reducing the body charge."""
        upload_bytes = max(0, upload_bytes)
        with self._changed:
            lease = self._generation_leases.get(generation)
            lifecycle = self._lifecycles.get(job_id)
            if (
                lease is None
                or not lease.active
                or lease.cancelled
                or lease.job_id != job_id
                or lifecycle is None
                or lifecycle.state != "creating"
                or lifecycle.generation != generation
            ):
                raise JobTerminal(job_id, lifecycle.state if lifecycle else "tombstoned")
            delta = upload_bytes - lease.reserved_memory_bytes
            if self._body_bytes + self._reserved_memory_bytes + delta > self.settings.memory_quota_bytes:
                raise StoreCapacityError("The in-flight image memory limit has been reached. Try again later.")
            lease.reserved_memory_bytes = upload_bytes
            self._reserved_memory_bytes += delta
            return lease.reserved_memory_bytes

    def reserve_resources(self, job_id: str, generation: str, upload_bytes: int, width: int, height: int) -> tuple[int, int]:
        """Reserve persistent PNG output and decoded/inference working-set bytes."""
        pixels = width * height
        disk_bytes = self._png_bound(width, height, 3) + self._png_bound(width, height, 1)
        memory_bytes = upload_bytes + pixels * (
            4 + self.settings.inference_working_bytes_per_pixel
        )
        with self._changed:
            lifecycle = self._lifecycles.get(job_id)
            lease = self._generation_leases.get(generation)
            if lifecycle is None or lifecycle.state != "creating" or lifecycle.generation != generation or lease is None or not lease.active or lease.cancelled:
                raise JobTerminal(job_id, lifecycle.state if lifecycle else "tombstoned")
            if lease.reserved_disk_bytes:
                return lease.reserved_disk_bytes, lease.reserved_memory_bytes
            memory_delta = max(0, memory_bytes - lease.reserved_memory_bytes)
            if self._disk_bytes + self._reserved_disk_bytes + disk_bytes > self.settings.disk_quota_bytes:
                raise StoreCapacityError("The temporary disk quota has been reached. Delete a job and try again.")
            if self._body_bytes + self._reserved_memory_bytes + memory_delta > self.settings.memory_quota_bytes:
                raise StoreCapacityError("The in-flight image memory limit has been reached. Try again later.")
            lease.reserved_disk_bytes = disk_bytes
            lease.reserved_memory_bytes += memory_delta
            self._reserved_disk_bytes += disk_bytes
            self._reserved_memory_bytes += memory_delta
            return disk_bytes, memory_bytes

    @staticmethod
    def _png_bound(width: int, height: int, channels: int) -> int:
        raw = (width * channels + 1) * height
        # Pillow/zlib builds vary slightly in their worst-case stream overhead.
        # Reserve slack here and enforce the bound with _MeteredWriter.
        deflate = raw + (raw >> 12) + (raw >> 14) + (raw >> 25) + raw // 1000 + 1037
        chunks = max(1, (deflate + 65535) // 65536)
        return 8 + 25 + deflate + chunks * 12 + 12

    def _release_reservation_locked(self, lease: GenerationLease) -> None:
        self._reserved_disk_bytes -= lease.reserved_disk_bytes
        self._reserved_memory_bytes -= lease.reserved_memory_bytes
        lease.reserved_disk_bytes = 0
        lease.reserved_memory_bytes = 0

    def fail_creation(self, job_id: str, generation: str, error: str) -> bool:
        return self.finalize_creation(job_id, generation, error)

    @staticmethod
    def _directory_bytes(directory: Path) -> tuple[int, bool]:
        total = 0
        complete = True

        def scan_error(_: OSError) -> None:
            nonlocal complete
            complete = False

        try:
            directory.stat()
            for root, _, files in os.walk(directory, onerror=scan_error):
                for name in files:
                    try:
                        total += (Path(root) / name).stat().st_size
                    except OSError:
                        complete = False
        except OSError:
            complete = False
        return total, complete

    def _quarantine(self, job_id: str, generation: str, directory: Path, error: BaseException, conservative_bytes: int = 0) -> Quarantine:
        scanned, complete = self._directory_bytes(directory)
        disk_bytes = scanned if complete else max(scanned, conservative_bytes)
        record = Quarantine(uuid.uuid4().hex, job_id, generation, directory, disk_bytes, str(error))
        with self._changed:
            lease = self._generation_leases.get(generation)
            if (
                lease is not None and lease.active and lease.job_id == job_id
                and lease.directory == directory and not lease.storage_transferred_to_quarantine
            ):
                lease.directory = None
                lease.storage_transferred_to_quarantine = True
            self._quarantines[record.id] = record
            self._disk_bytes += record.disk_bytes
            self._changed.notify_all()
        return record

    def _replace_generation_with_quarantine(
        self, lease: GenerationLease, directory: Path, error: BaseException, lifecycle_error: str
    ) -> Quarantine:
        """Keep the generation charged while scanning, then swap atomically."""
        scanned, complete = self._directory_bytes(directory)
        disk_bytes = scanned if complete else max(scanned, lease.reserved_disk_bytes)
        record = Quarantine(
            uuid.uuid4().hex, lease.job_id, lease.generation, directory, disk_bytes, str(error)
        )
        with self._changed:
            if self._generation_leases.get(lease.generation) is not lease or not lease.active:
                raise StoreDeletionError("Generation ownership changed during quarantine accounting.")
            lifecycle = self._lifecycles.get(lease.job_id)
            live_job = self._jobs.get(lease.job_id)
            if (
                live_job is not None
                and lifecycle is not None
                and lifecycle.state == "live"
                and lifecycle.job is live_job
                and lifecycle.generation == lease.generation
                and live_job.generation == lease.generation
            ):
                self._disk_bytes -= live_job.disk_bytes
            self._quarantines[record.id] = record
            self._disk_bytes += record.disk_bytes
            self._release_reservation_locked(lease)
            lease.active = False
            self._generation_leases.pop(lease.generation, None)
            if lifecycle is not None and lifecycle.generation == lease.generation:
                lifecycle.job = None
                lifecycle.state = "failed"
                lifecycle.error = lifecycle_error
                lifecycle.updated_at = time.monotonic()
            self._jobs.pop(lease.job_id, None)
            self._changed.notify_all()
        return record

    def cancel_generation(self, job_id: str, generation: str, error: str = "Job creation was cancelled.") -> bool:
        with self._changed:
            lease = self._generation_leases.get(generation)
            lifecycle = self._lifecycles.get(job_id)
            if (
                lease is None or not lease.active or lease.job_id != job_id
                or lifecycle is None or lifecycle.state != "creating"
                or lifecycle.generation != generation
            ):
                return False
            lease.cancelled = True
            lifecycle.state = "tombstoned"
            lifecycle.error = error
            lifecycle.updated_at = time.monotonic()
            self._changed.notify_all()
            return True

    def finalize_creation(self, job_id: str, generation: str, error: str | None = None) -> bool:
        with self._changed:
            lease = self._generation_leases.get(generation)
            if lease is None or not lease.active or lease.job_id != job_id:
                return False
            lifecycle = self._lifecycles.get(job_id)
            cancelled = (
                lease.cancelled
                or lifecycle is None
                or lifecycle.generation != generation
                or lifecycle.state == "tombstoned"
            )
            directory = lease.directory
            live_job = self._jobs.get(job_id)
            locked_job: Job | None = None
            try:
                if live_job is not None:
                    live_job.lock.acquire()
                    locked_job = live_job
                    lifecycle = self._lifecycles.get(job_id)
                    if not (
                        self._jobs.get(job_id) is live_job
                        and lifecycle is not None
                        and lifecycle.state == "live"
                        and lifecycle.job is live_job
                        and lifecycle.generation == generation
                        and live_job.generation == generation
                    ):
                        live_job.lock.release()
                        locked_job = None
                        live_job = None
                        directory = None

                cleanup_error: OSError | None = None
                released_for_partial_scan = live_job is None and (cancelled or error) and directory is not None
                if released_for_partial_scan:
                    self._changed.release()
                try:
                    if (cancelled or error) and directory is not None:
                        try:
                            shutil.rmtree(directory)
                        except FileNotFoundError:
                            pass
                        except OSError as exc:
                            cleanup_error = exc

                    if cleanup_error is not None and directory is not None:
                        self._replace_generation_with_quarantine(
                            lease, directory, cleanup_error, error or str(cleanup_error)
                        )
                        raise StoreDeletionError(
                            "Could not remove partial temporary job storage; cleanup remains tracked and must be retried."
                        ) from cleanup_error
                finally:
                    if released_for_partial_scan:
                        self._changed.acquire()

                lifecycle = self._lifecycles.get(job_id)
                if (
                    live_job is not None
                    and self._jobs.get(job_id) is live_job
                    and (cancelled or error)
                    and lifecycle is not None
                    and lifecycle.state == "live"
                    and lifecycle.job is live_job
                    and lifecycle.generation == generation
                ):
                    self._jobs.pop(job_id, None)
                    self._disk_bytes -= live_job.disk_bytes
                    lifecycle.job = None
                    lifecycle.state = "failed" if error else "tombstoned"
                    lifecycle.error = error
                    lifecycle.updated_at = time.monotonic()
                self._release_reservation_locked(lease)
                lease.active = False
                self._generation_leases.pop(generation, None)
                if lifecycle is not None and lifecycle.generation == generation:
                    if lifecycle.state == "creating":
                        lifecycle.state = "failed"
                        lifecycle.error = error or "Job creation did not complete."
                    lifecycle.updated_at = time.monotonic()
                self._changed.notify_all()
                return True
            finally:
                if locked_job is not None:
                    locked_job.lock.release()

    def release_worker_memory(self, job_id: str, generation: str) -> bool:
        """Release worker memory after local image objects have been dropped."""
        with self._changed:
            lease = self._generation_leases.get(generation)
            if lease is None or not lease.active or lease.job_id != job_id:
                return False
            lifecycle = self._lifecycles.get(job_id)
            if lease.storage_transferred_to_quarantine:
                self._release_reservation_locked(lease)
                lease.active = False
                self._generation_leases.pop(generation, None)
                self._changed.notify_all()
                return True
            clean_live = (
                not lease.cancelled and lifecycle is not None
                and lifecycle.state == "live" and lifecycle.generation == generation
                and self._jobs.get(job_id) is lifecycle.job
            )
            if clean_live:
                self._reserved_memory_bytes -= lease.reserved_memory_bytes
                lease.reserved_memory_bytes = 0
                lease.active = False
                self._generation_leases.pop(generation, None)
                self._changed.notify_all()
                return True
        return self.finalize_creation(job_id, generation, "Job creation was cancelled.")

    def shutdown(self) -> None:
        with self._changed:
            # Close admission before cancellation or cleanup. A generation that
            # already crossed the publication commit point remains live while
            # its worker drops decoded/inference memory.
            self._closing = True
            for lease in self._generation_leases.values():
                if lease.active:
                    lifecycle = self._lifecycles.get(lease.job_id)
                    if (
                        lifecycle is not None
                        and lifecycle.state == "creating"
                        and lifecycle.generation == lease.generation
                    ):
                        lease.cancelled = True
                        lifecycle.state = "failed"
                        lifecycle.error = "Backend shutdown cancelled creation."
                        lifecycle.updated_at = time.monotonic()
            self._changed.notify_all()
            deadline = time.monotonic() + max(0, self.settings.shutdown_wait_seconds)
            while (
                any(lease.active for lease in self._generation_leases.values())
                or self._body_leases
                or self._render_leases
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._changed.wait(remaining)
            job_ids = list(self._jobs)

        for job_id in job_ids:
            with self._lock:
                owner_active = any(
                    lease.active and lease.job_id == job_id
                    for lease in self._generation_leases.values()
                )
            if owner_active:
                continue
            try:
                self.delete(job_id, tombstone=False)
            except (StoreDeletionError, JobTerminal, JobNotFound):
                pass
        self._cleanup_quarantines()

        # Report only unresolved current evidence, not failures from attempts
        # that a later retry in this same shutdown successfully removed.
        with self._lock:
            failures = [
                *(f"generation:{lease.generation}" for lease in self._generation_leases.values() if lease.active),
                *(f"job:{job_id}" for job_id in self._jobs),
                *(f"body:{lease_id}" for lease_id in self._body_leases),
                *(f"render:{lease_id}" for lease_id in self._render_leases),
                *(
                    f"quarantine:{quarantine_id}:{record.job_id}"
                    for quarantine_id, record in self._quarantines.items()
                ),
            ]
        if not failures:
            self._release_process_lock()
        if failures:
            raise StoreDeletionError("Could not remove temporary storage for job(s): " + ", ".join(failures) + ". Cleanup remains required before the next startup.")

    @staticmethod
    def _save_private(image: Image.Image, path: Path, max_bytes: int | None = None) -> None:
        if max_bytes is None:
            channels = 1 if image.mode == "L" else 3
            max_bytes = JobStore._png_bound(image.width, image.height, channels)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                image.save(_MeteredWriter(handle, max_bytes), format="PNG", optimize=True)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
            raise

    def create(self, original: Image.Image, mask: Image.Image, job_id: str, generation: str) -> Job:
        job_id = normalize_job_id(job_id)
        with self._lock:
            lifecycle = self._lifecycles.get(job_id)
            lease = self._generation_leases.get(generation)
            if lifecycle is None or lifecycle.state != "creating" or lifecycle.generation != generation or lease is None or not lease.active or lease.cancelled:
                raise JobTerminal(job_id, lifecycle.state if lifecycle else "tombstoned")
            if not lease.reserved_disk_bytes:
                raise StoreCapacityError("Job resources were not reserved before file creation.")
        directory = self.root / f"job-{job_id}-{generation}"
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError as exc:
            message = str(exc) or "The requested job id collides with existing storage."
            exc.__traceback__ = None
            del exc, original, mask
            raise StoreCreationError("capacity", message) from None
        with self._changed:
            lease = self._generation_leases[generation]
            lease.directory = directory
        try:
            self._save_private(original, directory / "original.png")
            self._save_private(mask, directory / "mask.png")
            disk_bytes, complete = self._directory_bytes(directory)
            if not complete:
                raise StoreCapacityError("Could not verify encoded job storage.")
            with self._changed:
                lifecycle = self._lifecycles.get(job_id)
                lease = self._generation_leases.get(generation)
                if lifecycle is None or lifecycle.state != "creating" or lifecycle.generation != generation or lease is None or not lease.active or lease.cancelled:
                    raise JobTerminal(job_id, lifecycle.state if lifecycle else "tombstoned")
                if disk_bytes > lease.reserved_disk_bytes:
                    raise StoreCapacityError("Encoded job storage exceeded its conservative reservation.")
                now = time.monotonic()
                job = Job(job_id, directory, original.width, original.height, now, now, disk_bytes, generation)
                # Publication converts disk reservation but retains worker memory
                # until the worker has dropped decoded/inference objects.
                self._reserved_disk_bytes -= lease.reserved_disk_bytes
                lease.reserved_disk_bytes = 0
                self._jobs[job_id] = job
                self._disk_bytes += disk_bytes
                lifecycle.state = "live"
                lifecycle.generation = generation
                lifecycle.updated_at = now
                lifecycle.job = job
                self._changed.notify_all()
                return job
        except BaseException as original_error:
            if isinstance(original_error, JobTerminal):
                classification = "terminal"
            elif isinstance(original_error, StoreCapacityError):
                classification = "capacity"
            elif isinstance(original_error, StoreDeletionError):
                classification = "cleanup"
            else:
                classification = "generation"
            message = str(original_error) or type(original_error).__name__
            original_traceback = original_error.__traceback__
            with contextlib.suppress(RuntimeError):
                if original_traceback is not None:
                    traceback.clear_frames(original_traceback)
            original_error.__traceback__ = None
            del original_traceback, original_error, original, mask

            try:
                shutil.rmtree(directory)
            except FileNotFoundError:
                pass
            except OSError as cleanup_error:
                cleanup_message = (
                    "Could not remove partial temporary job storage; "
                    f"cleanup remains tracked and must be retried: {cleanup_error}"
                )
                with self._changed:
                    lease = self._generation_leases.get(generation)
                if lease is None or not lease.active or lease.job_id != job_id:
                    raise StoreDeletionError(
                        "Generation ownership changed during partial-create cleanup."
                    ) from cleanup_error
                self._replace_generation_with_quarantine(
                    lease, directory, cleanup_error, cleanup_message
                )
                cleanup_error.__traceback__ = None
                del cleanup_error
                raise StoreCreationError("cleanup", cleanup_message) from None
            raise StoreCreationError(classification, message) from None

    @contextlib.contextmanager
    def locked(self, job_id: str) -> Iterator[Job]:
        try:
            job_id = normalize_job_id(job_id)
        except ValueError as exc:
            raise JobNotFound(job_id) from exc
        with self._lock:
            self._forget_terminal_locked(time.monotonic())
            job = self._jobs.get(job_id)
            if job is None:
                lifecycle = self._lifecycles.get(job_id)
                if lifecycle is not None and lifecycle.state == "creating":
                    raise JobPending(job_id)
                if lifecycle is not None and lifecycle.state in ("failed", "tombstoned"):
                    raise JobTerminal(job_id, lifecycle.state)
                if job_id in self._used_job_ids:
                    raise JobTerminal(job_id, "tombstoned")
                raise JobNotFound(job_id)
            job.lock.acquire()
            lifecycle = self._lifecycles.get(job_id)
            if not (
                self._jobs.get(job_id) is job
                and lifecycle is not None
                and lifecycle.state == "live"
                and lifecycle.job is job
                and lifecycle.generation == job.generation
            ):
                job.lock.release()
                if lifecycle is not None and lifecycle.state == "creating":
                    raise JobPending(job_id)
                if lifecycle is not None and lifecycle.state in ("failed", "tombstoned"):
                    raise JobTerminal(job_id, lifecycle.state)
                raise JobNotFound(job_id)
            job.last_access = time.monotonic()
        try:
            yield job
        finally:
            job.lock.release()

    def _terminalize_live_after_delete_locked(self, job_id: str, job: Job, tombstone: bool, error: BaseException | None = None) -> None:
        if self._jobs.get(job_id) is not job:
            return
        self._jobs.pop(job_id, None)
        self._disk_bytes -= job.disk_bytes
        lifecycle = self._lifecycles.get(job_id)
        if lifecycle is None or lifecycle.job is not job or lifecycle.generation != job.generation:
            return
        lifecycle.job = None
        lifecycle.updated_at = time.monotonic()
        lifecycle.error = str(error) if error else None
        lifecycle.state = "failed" if error else ("tombstoned" if tombstone else "failed")
        self._changed.notify_all()

    def delete(self, job_id: str, tombstone: bool = True) -> bool:
        job_id = normalize_job_id(job_id)
        with self._changed:
            self._forget_terminal_locked(time.monotonic())
            lifecycle = self._lifecycles.get(job_id)
            if lifecycle is None:
                if job_id in self._used_job_ids:
                    raise JobTerminal(job_id, "tombstoned")
                raise JobNotFound(job_id)
            lease = self._generation_leases.get(lifecycle.generation or "")
            if lease is not None and lease.active and lifecycle.state == "creating":
                if lifecycle.state in ("tombstoned", "failed"):
                    raise JobTerminal(job_id, lifecycle.state)
                lease.cancelled = True
                lifecycle.state = "tombstoned" if tombstone else "failed"
                lifecycle.error = None if tombstone else "Job creation was cancelled."
                lifecycle.updated_at = time.monotonic()
                self._changed.notify_all()
                return True
            if lease is not None and lease.active and lifecycle.state == "live":
                lease.cancelled = True
            if lifecycle.state in ("tombstoned", "failed"):
                raise JobTerminal(job_id, lifecycle.state)
            if lifecycle.state == "creating":
                lifecycle.state = "tombstoned"
                lifecycle.updated_at = time.monotonic()
                self._changed.notify_all()
                return True
            job = self._jobs.get(job_id)
            if job is None:
                lifecycle.state = "failed"
                lifecycle.job = None
                lifecycle.updated_at = time.monotonic()
                return False
            job.lock.acquire()
            try:
                lifecycle = self._lifecycles.get(job_id)
                if not (
                    self._jobs.get(job_id) is job
                    and lifecycle is not None
                    and lifecycle.state == "live"
                    and lifecycle.job is job
                    and lifecycle.generation == job.generation
                ):
                    if lifecycle is not None and lifecycle.state in ("failed", "tombstoned"):
                        raise JobTerminal(job_id, lifecycle.state)
                    raise JobNotFound(job_id)
                try:
                    shutil.rmtree(job.directory)
                except FileNotFoundError:
                    self._terminalize_live_after_delete_locked(job_id, job, tombstone)
                except OSError as exc:
                    # rmtree may already have destroyed part of the job. It can no
                    # longer remain readable/live; account only what is still present.
                    self._terminalize_live_after_delete_locked(job_id, job, tombstone, exc)
                    self._quarantine(job_id, job.generation, job.directory, exc, job.disk_bytes)
                    raise StoreDeletionError("Could not completely remove the job; it is terminal and remaining storage is quarantined for retry.") from exc
                else:
                    self._terminalize_live_after_delete_locked(job_id, job, tombstone)
            finally:
                job.lock.release()
        return True

    def _delete_if_expired(self, job_id: str, candidate: Job, current: float) -> bool:
        with self._changed:
            if self._jobs.get(job_id) is not candidate:
                return False
            candidate.lock.acquire()
            try:
                lifecycle = self._lifecycles.get(job_id)
                if self._jobs.get(job_id) is not candidate or lifecycle is None or lifecycle.state != "live" or lifecycle.job is not candidate or current - candidate.last_access < self.settings.job_ttl_seconds:
                    return False
                try:
                    shutil.rmtree(candidate.directory)
                except FileNotFoundError:
                    self._terminalize_live_after_delete_locked(job_id, candidate, True)
                except OSError as exc:
                    self._terminalize_live_after_delete_locked(job_id, candidate, True, exc)
                    self._quarantine(job_id, candidate.generation, candidate.directory, exc, candidate.disk_bytes)
                    raise StoreDeletionError("Could not completely remove expired job storage.") from exc
                else:
                    self._terminalize_live_after_delete_locked(job_id, candidate, True)
                return True
            finally:
                candidate.lock.release()

    def _cleanup_quarantine(self, quarantine_id: str) -> bool:
        with self._lock:
            record = self._quarantines.get(quarantine_id)
        if record is None:
            return False
        try:
            shutil.rmtree(record.directory)
        except FileNotFoundError:
            pass
        except OSError as exc:
            # Recompute independently; never touch the public lifecycle.
            scanned, complete = self._directory_bytes(record.directory)
            replacement = Quarantine(
                record.id,
                record.job_id,
                record.generation,
                record.directory,
                scanned if complete else max(scanned, record.disk_bytes),
                str(exc),
            )
            with self._changed:
                if self._quarantines.get(quarantine_id) is record:
                    self._disk_bytes += replacement.disk_bytes - record.disk_bytes
                    self._quarantines[quarantine_id] = replacement
            raise StoreDeletionError("Could not remove quarantined temporary storage; retry cleanup.") from exc
        with self._changed:
            current = self._quarantines.get(quarantine_id)
            if current is not None and current.directory == record.directory and current.generation == record.generation:
                self._disk_bytes -= current.disk_bytes
                self._quarantines.pop(quarantine_id, None)
                self._changed.notify_all()
                return True
        return False

    def _cleanup_quarantines(self, failures: list[str] | None = None) -> int:
        with self._lock:
            ids = list(self._quarantines)
        removed = 0
        for quarantine_id in ids:
            try:
                removed += int(self._cleanup_quarantine(quarantine_id))
            except StoreDeletionError:
                if failures is not None:
                    failures.append(f"quarantine:{quarantine_id}")
        return removed

    def cleanup_expired(self, now: float | None = None) -> int:
        current = time.monotonic() if now is None else now
        removed = 0
        with self._lock:
            candidates = [(job_id, job) for job_id, job in self._jobs.items() if current - job.last_access >= self.settings.job_ttl_seconds]
            stale_creating = [
                (job_id, lifecycle.generation)
                for job_id, lifecycle in self._lifecycles.items()
                if lifecycle.state == "creating"
                and current - lifecycle.updated_at >= self.settings.job_ttl_seconds
                and (
                    lifecycle.generation is None
                    or lifecycle.generation not in self._generation_leases
                    or not self._generation_leases[lifecycle.generation].active
                )
            ]
            for job_id, generation in stale_creating:
                lifecycle = self._lifecycles.get(job_id)
                if lifecycle is not None and lifecycle.state == "creating" and lifecycle.generation == generation:
                    lifecycle.state = "failed"
                    lifecycle.error = "Stale job creation was recovered."
                    lifecycle.updated_at = current
                    removed += 1
        for job_id, candidate in candidates:
            try:
                if self._delete_if_expired(job_id, candidate, current):
                    removed += 1
            except StoreDeletionError:
                continue
        removed += self._cleanup_quarantines()
        with self._lock:
            self._forget_terminal_locked(current)
        return removed

    def get(self, job_id: str) -> Job:
        with self.locked(job_id) as job:
            return job

    def append_stroke(self, job_id: str, stroke: MaskStroke) -> tuple[int, int]:
        with self.locked(job_id) as job:
            if len(job.strokes) >= MAX_STROKES_PER_JOB:
                raise StrokeLimitError(f"A job may contain at most {MAX_STROKES_PER_JOB} strokes.")
            job.strokes.append(stroke)
            job.revision += 1
            return job.revision, len(job.strokes)

    def undo_stroke(self, job_id: str) -> tuple[int, int]:
        with self.locked(job_id) as job:
            if job.strokes:
                job.strokes.pop()
                job.revision += 1
            return job.revision, len(job.strokes)

    def reset_strokes(self, job_id: str) -> tuple[int, int]:
        with self.locked(job_id) as job:
            if job.strokes:
                job.strokes.clear()
                job.revision += 1
            return job.revision, 0

    def read_images(self, job_id: str) -> tuple[Image.Image, Image.Image]:
        original, mask, _ = self.read_render_data(job_id)
        return original, mask

    def read_render_data(self, job_id: str) -> tuple[Image.Image, Image.Image, tuple[MaskStroke, ...]]:
        with self.locked(job_id) as job:
            with Image.open(job.original_path) as original_source:
                original = original_source.copy()
            with Image.open(job.mask_path) as mask_source:
                mask = mask_source.copy()
            strokes = tuple(job.strokes)
        return original, mask, strokes

    def stats(self) -> tuple[int, int]:
        with self._lock:
            return len(self._jobs), self._disk_bytes + self._reserved_disk_bytes
