from __future__ import annotations

import base64
import io

import httpx
import pytest
from PIL import Image

from app.config import Settings
from app.remover import BiRefNetHRRemover
from app.runpod_remover import (
    CANVAS_SIZE,
    RunpodConfigurationError,
    RunpodInferenceError,
    RunpodRemover,
    build_default_remover,
)


def png_base64(image: Image.Image) -> str:
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return base64.b64encode(stream.getvalue()).decode("ascii")


def client_factory(handler):
    def factory(**kwargs):
        return httpx.Client(
            transport=httpx.MockTransport(handler),
            **kwargs,
        )

    return factory


def test_runpod_remover_sends_square_canvas_and_restores_size():
    seen = {}

    def handler(request: httpx.Request):
        seen["authorization"] = request.headers["Authorization"]
        seen["worker_token"] = request.headers[
            "X-Background-Studio-Token"
        ]
        payload = __import__("json").loads(request.content)
        canvas = Image.open(
            io.BytesIO(
                base64.b64decode(payload["image_base64"])
            )
        )
        canvas.load()
        seen["canvas"] = canvas
        mask = Image.new(
            "L",
            (CANVAS_SIZE, CANVAS_SIZE),
            255,
        )
        return httpx.Response(
            200,
            json={"mask_base64": png_base64(mask)},
        )

    remover = RunpodRemover(
        "https://example.api.runpod.ai",
        "runpod-api-key",
        "secret-token",
        client_factory=client_factory(handler),
    )
    result = remover.remove(
        Image.new("RGB", (20, 10), "red")
    )

    assert result.mode == "L"
    assert result.size == (20, 10)
    assert result.getextrema() == (255, 255)
    assert seen["authorization"] == "Bearer runpod-api-key"
    assert seen["worker_token"] == "secret-token"
    assert seen["canvas"].size == (CANVAS_SIZE, CANVAS_SIZE)
    assert seen["canvas"].getpixel((0, 0)) == (0, 0, 0)
    assert seen["canvas"].getpixel((512, 512)) == (255, 0, 0)


def test_runpod_remover_uses_configured_high_resolution_canvas():
    seen = {}

    def handler(request: httpx.Request):
        payload = __import__("json").loads(request.content)
        canvas = Image.open(
            io.BytesIO(
                base64.b64decode(payload["image_base64"])
            )
        )
        canvas.load()
        seen["canvas_size"] = canvas.size
        mask = Image.new(
            "L",
            (2048, 2048),
            255,
        )
        return httpx.Response(
            200,
            json={"mask_base64": png_base64(mask)},
        )

    remover = RunpodRemover(
        "https://example.api.runpod.ai",
        "api-key",
        "token",
        canvas_size=2048,
        client_factory=client_factory(handler),
    )
    result = remover.remove(Image.new("RGB", (20, 10), "red"))

    assert seen["canvas_size"] == (2048, 2048)
    assert result.size == (20, 10)
    assert result.getextrema() == (255, 255)


def test_runpod_remover_tiles_oversized_images_before_inference():
    seen = {"calls": 0, "sizes": []}

    def handler(request: httpx.Request):
        seen["calls"] += 1
        payload = __import__("json").loads(request.content)
        canvas = Image.open(
            io.BytesIO(
                base64.b64decode(payload["image_base64"])
            )
        )
        canvas.load()
        seen["sizes"].append(canvas.size)
        return httpx.Response(
            200,
            json={
                "mask_base64": png_base64(
                    Image.new("L", canvas.size, 255)
                ),
            },
        )

    remover = RunpodRemover(
        "https://example.api.runpod.ai",
        "api-key",
        "token",
        canvas_size=1024,
        client_factory=client_factory(handler),
    )
    result = remover.remove(Image.new("RGB", (2300, 2300), "red"))

    assert seen["calls"] == 4
    assert seen["sizes"] == [(1024, 1024)] * 4
    assert result.size == (2300, 2300)
    assert result.getextrema() == (255, 255)


@pytest.mark.parametrize("canvas_size", [512, 3072])
def test_runpod_remover_rejects_unsupported_canvas_size(canvas_size):
    with pytest.raises(
        RunpodConfigurationError,
        match="canvas size",
    ):
        RunpodRemover(
            "https://example.api.runpod.ai",
            "api-key",
            "token",
            canvas_size=canvas_size,
        )


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.api.runpod.ai",
        "https://user@example.api.runpod.ai",
        "https://example.api.runpod.ai?token=nope",
    ],
)
def test_runpod_remover_requires_clean_https_endpoint(endpoint):
    with pytest.raises(RunpodConfigurationError):
        RunpodRemover(endpoint, "api-key", "token")


def test_runpod_remover_rejects_wrong_mask_dimensions():
    def handler(_):
        return httpx.Response(
            200,
            json={
                "mask_base64": png_base64(
                    Image.new("L", (8, 8))
                )
            },
        )

    remover = RunpodRemover(
        "https://example.api.runpod.ai",
        "api-key",
        "token",
        client_factory=client_factory(handler),
    )

    with pytest.raises(
        RunpodInferenceError,
        match="wrong dimensions",
    ):
        remover.remove(Image.new("RGB", (4, 3)))


def test_runpod_remover_does_not_retry_ambiguous_read_timeout():
    calls = 0

    def handler(_):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timed out")

    remover = RunpodRemover(
        "https://example.api.runpod.ai",
        "api-key",
        "token",
        client_factory=client_factory(handler),
    )

    with pytest.raises(
        RunpodInferenceError,
        match="not retried",
    ):
        remover.remove(Image.new("RGB", (4, 3)))

    assert calls == 1


def test_runpod_remover_retries_cold_start_statuses(monkeypatch):
    statuses = iter([430, 502, 200])
    sleeps = []
    calls = 0

    def handler(_):
        nonlocal calls
        calls += 1
        status = next(statuses)
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(
            200,
            json={
                "mask_base64": png_base64(
                    Image.new(
                        "L",
                        (CANVAS_SIZE, CANVAS_SIZE),
                        255,
                    )
                )
            },
        )

    monkeypatch.setattr(
        "app.runpod_remover.time.sleep",
        sleeps.append,
    )
    remover = RunpodRemover(
        "https://example.api.runpod.ai",
        "api-key",
        "token",
        client_factory=client_factory(handler),
    )

    result = remover.remove(Image.new("RGB", (4, 3)))

    assert result.size == (4, 3)
    assert calls == 3
    assert sleeps == [10.0, 10.0]


def test_build_default_remover_falls_back_when_keychain_is_empty(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.runpod_remover._keychain_password",
        lambda service, account: None,
    )

    remover = build_default_remover(Settings())

    assert isinstance(remover, BiRefNetHRRemover)


def test_build_default_remover_requires_complete_runpod_config(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.runpod_remover._keychain_password",
        lambda service, account: (
            "https://example.api.runpod.ai"
            if account == "endpoint-url"
            else "worker-token"
            if account == "worker-token"
            else None
        ),
    )

    with pytest.raises(
        RunpodConfigurationError,
        match="incomplete",
    ):
        build_default_remover(
            Settings(remover_backend="runpod")
        )
