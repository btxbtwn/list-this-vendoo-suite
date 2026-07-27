from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app


class FakeRemover:
    def __init__(self, value: int = 255) -> None:
        self.value = value
        self.calls = 0
        self.sizes: list[tuple[int, int]] = []

    def remove(
        self,
        image: Image.Image,
    ) -> Image.Image:
        self.calls += 1
        self.sizes.append(image.size)
        return Image.new(
            "L",
            image.size,
            self.value,
        )


def image_bytes(
    fmt: str = "PNG",
    size: tuple[int, int] = (4, 3),
    color=(200, 10, 20),
    exif=None,
) -> bytes:
    stream = io.BytesIO()
    image = Image.new(
        "RGB",
        size,
        color,
    )
    image.save(
        stream,
        format=fmt,
        exif=exif,
    )
    return stream.getvalue()


@pytest.fixture
def app_factory(tmp_path: Path):
    clients: list[TestClient] = []

    def make(
        remover: FakeRemover | None = None,
        **overrides,
    ):
        defaults = dict(
            max_upload_bytes=1024 * 1024,
            max_pixels=1_000_000,
            max_jobs=4,
            disk_quota_bytes=10 * 1024 * 1024,
            job_ttl_seconds=60,
            cleanup_interval_seconds=3600,
            preview_max_side=100,
            temp_root=(
                tmp_path
                / f"jobs-{len(clients)}"
            ),
            enforce_loopback=False,
            process_lock=False,
        )
        defaults.update(overrides)

        fake = remover or FakeRemover()
        app = create_app(
            Settings(**defaults),
            fake,
        )
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return app, client, fake

    yield make

    for client in reversed(clients):
        client.__exit__(
            None,
            None,
            None,
        )
