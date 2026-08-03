from __future__ import annotations

import base64
import io
import os
import sys
import threading
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2]),
)
os.environ["BACKGROUND_STUDIO_WORKER_TOKEN"] = "module-test-token"

from runpod.worker import CANVAS_SIZE, create_app  # noqa: E402


def png_bytes(size=(CANVAS_SIZE, CANVAS_SIZE)) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", size, "blue").save(
        stream,
        format="PNG",
    )
    return stream.getvalue()


class FakeEngine:
    def __init__(self) -> None:
        self.calls = 0

    def remove(self, image_bytes: bytes) -> bytes:
        self.calls += 1
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.load()
            if image.size != (CANVAS_SIZE, CANVAS_SIZE):
                raise ValueError(
                    "Image dimensions must be 1024x1024."
                )
        stream = io.BytesIO()
        Image.new(
            "L",
            (CANVAS_SIZE, CANVAS_SIZE),
            127,
        ).save(stream, format="PNG")
        return stream.getvalue()


def test_worker_authenticates_and_returns_mask():
    engine = FakeEngine()
    with TestClient(
        create_app(engine=engine, token="test-token")
    ) as client:
        response = client.post(
            "/remove",
            headers={
                "X-Background-Studio-Token": "test-token"
            },
            json={
                "image_base64": base64.b64encode(
                    png_bytes()
                ).decode("ascii")
            },
        )

    assert response.status_code == 200
    assert engine.calls == 1
    mask = Image.open(
        io.BytesIO(
            base64.b64decode(
                response.json()["mask_base64"]
            )
        )
    )
    mask.load()
    assert mask.mode == "L"
    assert mask.size == (CANVAS_SIZE, CANVAS_SIZE)


def test_worker_rejects_missing_or_wrong_token():
    engine = FakeEngine()
    with TestClient(
        create_app(engine=engine, token="test-token")
    ) as client:
        missing = client.post(
            "/remove",
            json={
                "image_base64": base64.b64encode(
                    png_bytes()
                ).decode("ascii")
            },
        )
        wrong = client.post(
            "/remove",
            headers={
                "X-Background-Studio-Token": "wrong"
            },
            json={
                "image_base64": base64.b64encode(
                    png_bytes()
                ).decode("ascii")
            },
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert engine.calls == 0


def test_worker_rejects_bad_base64_and_wrong_dimensions():
    engine = FakeEngine()
    headers = {
        "X-Background-Studio-Token": "test-token"
    }
    with TestClient(
        create_app(engine=engine, token="test-token")
    ) as client:
        malformed = client.post(
            "/remove",
            headers=headers,
            json={"image_base64": "not base64!"},
        )
        wrong_size = client.post(
            "/remove",
            headers=headers,
            json={
                "image_base64": base64.b64encode(
                    png_bytes((32, 32))
                ).decode("ascii")
            },
        )

    assert malformed.status_code == 422
    assert wrong_size.status_code == 422
    assert engine.calls == 1


def test_worker_rejects_oversized_body_before_json_parsing():
    engine = FakeEngine()
    with TestClient(
        create_app(engine=engine, token="test-token")
    ) as client:
        response = client.post(
            "/remove",
            headers={
                "X-Background-Studio-Token": "test-token",
                "Content-Type": "application/json",
            },
            content=b"x" * (12 * 1024 * 1024 + 1),
        )

    assert response.status_code == 413
    assert engine.calls == 0


def test_worker_constructs_and_runs_engine_on_same_thread():
    thread_ids = {}

    class ThreadBoundEngine(FakeEngine):
        def __init__(self):
            super().__init__()
            thread_ids["constructed"] = threading.get_ident()

        def remove(self, image_bytes: bytes) -> bytes:
            thread_ids["inference"] = threading.get_ident()
            return super().remove(image_bytes)

    with TestClient(
        create_app(
            engine_factory=ThreadBoundEngine,
            token="test-token",
        )
    ) as client:
        response = client.post(
            "/remove",
            headers={
                "X-Background-Studio-Token": "test-token"
            },
            json={
                "image_base64": base64.b64encode(
                    png_bytes()
                ).decode("ascii")
            },
        )

    assert response.status_code == 200
    assert thread_ids["constructed"] == thread_ids["inference"]
