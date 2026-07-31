from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None else int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value is None else float(value)


@dataclass(frozen=True)
class Settings:
    max_upload_bytes: int = 25 * 1024 * 1024
    max_pixels: int = 40_000_000
    max_jobs: int = 12
    terminal_registry_max: int = 4096
    disk_quota_bytes: int = 1536 * 1024 * 1024
    memory_quota_bytes: int = 3 * 1024 * 1024 * 1024
    inference_working_bytes_per_pixel: int = 8
    inflight_body_quota_bytes: int = 100 * 1024 * 1024
    request_overhead_bytes: int = 1024 * 1024
    job_ttl_seconds: int = 30 * 60
    cleanup_interval_seconds: int = 30
    preview_max_side: int = 1400
    temp_root: Path = Path(tempfile.gettempdir()) / "background-studio"
    enforce_loopback: bool = True
    process_lock: bool = True
    shutdown_wait_seconds: int = 5
    remover_backend: str = "auto"
    runpod_keychain_service: str = "background-studio-runpod"
    runpod_connect_timeout_seconds: float = 10.0
    runpod_read_timeout_seconds: float = 300.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            max_upload_bytes=_env_int(
                "BACKGROUND_STUDIO_MAX_UPLOAD_BYTES",
                25 * 1024 * 1024,
            ),
            max_pixels=_env_int(
                "BACKGROUND_STUDIO_MAX_PIXELS",
                40_000_000,
            ),
            max_jobs=_env_int(
                "BACKGROUND_STUDIO_MAX_JOBS",
                12,
            ),
            terminal_registry_max=_env_int(
                "BACKGROUND_STUDIO_TERMINAL_REGISTRY_MAX",
                4096,
            ),
            disk_quota_bytes=_env_int(
                "BACKGROUND_STUDIO_DISK_QUOTA_BYTES",
                1536 * 1024 * 1024,
            ),
            memory_quota_bytes=_env_int(
                "BACKGROUND_STUDIO_MEMORY_QUOTA_BYTES",
                3 * 1024 * 1024 * 1024,
            ),
            inference_working_bytes_per_pixel=_env_int(
                "BACKGROUND_STUDIO_INFERENCE_WORKING_BYTES_PER_PIXEL",
                8,
            ),
            inflight_body_quota_bytes=_env_int(
                "BACKGROUND_STUDIO_INFLIGHT_BODY_QUOTA_BYTES",
                100 * 1024 * 1024,
            ),
            request_overhead_bytes=_env_int(
                "BACKGROUND_STUDIO_REQUEST_OVERHEAD_BYTES",
                1024 * 1024,
            ),
            job_ttl_seconds=_env_int(
                "BACKGROUND_STUDIO_JOB_TTL_SECONDS",
                30 * 60,
            ),
            cleanup_interval_seconds=_env_int(
                "BACKGROUND_STUDIO_CLEANUP_INTERVAL_SECONDS",
                30,
            ),
            preview_max_side=_env_int(
                "BACKGROUND_STUDIO_PREVIEW_MAX_SIDE",
                1400,
            ),
            shutdown_wait_seconds=_env_int(
                "BACKGROUND_STUDIO_SHUTDOWN_WAIT_SECONDS",
                5,
            ),
            remover_backend=os.getenv(
                "BACKGROUND_STUDIO_REMOVER_BACKEND",
                "auto",
            ).strip().lower(),
            runpod_keychain_service=os.getenv(
                "BACKGROUND_STUDIO_RUNPOD_KEYCHAIN_SERVICE",
                "background-studio-runpod",
            ),
            runpod_connect_timeout_seconds=_env_float(
                "BACKGROUND_STUDIO_RUNPOD_CONNECT_TIMEOUT_SECONDS",
                10.0,
            ),
            runpod_read_timeout_seconds=_env_float(
                "BACKGROUND_STUDIO_RUNPOD_READ_TIMEOUT_SECONDS",
                300.0,
            ),
            temp_root=Path(
                os.getenv(
                    "BACKGROUND_STUDIO_TEMP_ROOT",
                    Path(tempfile.gettempdir()) / "background-studio",
                )
            ),
        )
