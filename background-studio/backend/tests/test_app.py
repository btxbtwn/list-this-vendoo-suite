from __future__ import annotations

import asyncio
import io
import os
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.images import decode_upload
from app.main import RequestBodyLimitMiddleware, _read_limited, create_app
from app.store import JobPending, JobStore, JobTerminal, StoreCapacityError, StoreDeletionError

from conftest import FakeRemover, image_bytes


def upload(
    client,
    data: bytes,
    name: str = "photo.png",
    content_type: str = "image/png",
):
    return client.post(
        "/api/jobs",
        files={
            "file": (
                name,
                data,
                content_type,
            )
        },
    )


def append_stroke(
    client,
    job_id: str,
    mode: str,
    radius: float = 0.2,
    softness: float = 0.0,
    points=None,
):
    return client.post(
        f"/api/jobs/{job_id}/strokes",
        json={
            "mode": mode,
            "radius": radius,
            "softness": softness,
            "points": points or [
                [0.4, 0.5],
                [0.6, 0.5],
            ],
        },
    )


def response_image(
    response,
) -> Image.Image:
    return Image.open(
        io.BytesIO(response.content)
    ).convert("RGBA")


def center_alpha(
    response,
) -> int:
    image = response_image(response)
    return image.getpixel(
        (image.width // 2, image.height // 2)
    )[3]


def split_image_bytes(
    size: tuple[int, int] = (40, 40),
    textured: bool = False,
    subject_color=(220, 30, 30),
    background_color=(20, 60, 220),
    texture_color=(30, 30, 30),
) -> bytes:
    image = Image.new(
        "RGB",
        size,
        subject_color,
    )
    image.paste(
        background_color,
        (
            size[0] // 2,
            0,
            size[0],
            size[1],
        ),
    )
    if textured:
        image.paste(
            texture_color,
            (5, 15, 11, 26),
        )
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def shirt_on_white_bytes(
    size: tuple[int, int] = (40, 40),
) -> bytes:
    image = Image.new(
        "RGB",
        size,
        (245, 245, 240),
    )
    image.paste(
        (105, 20, 45),
        (0, 0, size[0] // 2, size[1]),
    )
    image.putpixel(
        (10, 20),
        (245, 245, 240),
    )
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def fragmented_background_bytes(
    size: tuple[int, int] = (640, 640),
) -> bytes:
    image = Image.new(
        "RGB",
        size,
        (220, 220, 215),
    )
    image.paste(
        (18, 18, 18),
        (0, 0, size[0] * 7 // 16, size[1]),
    )
    for box, color in [
        ((430, 220, 442, 232), (90, 40, 120)),
        ((440, 226, 449, 235), (50, 130, 70)),
        ((465, 340, 477, 352), (150, 70, 45)),
        ((500, 390, 514, 404), (40, 40, 40)),
    ]:
        image.paste(color, box)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


class PartialForegroundRemover:
    def remove(
        self,
        image: Image.Image,
    ) -> Image.Image:
        mask = Image.new(
            "L",
            image.size,
            0,
        )
        mask.paste(
            255,
            (
                0,
                0,
                14,
                image.height,
            ),
        )
        return mask


def test_batch_lifecycle_defaults_and_env_overrides(monkeypatch):
    monkeypatch.delenv("BACKGROUND_STUDIO_MAX_JOBS", raising=False)
    monkeypatch.delenv("BACKGROUND_STUDIO_TERMINAL_REGISTRY_MAX", raising=False)

    assert Settings().max_jobs == 12
    assert Settings().terminal_registry_max == 4096
    defaults = Settings.from_env()
    assert defaults.max_jobs == 12
    assert defaults.terminal_registry_max == 4096

    monkeypatch.setenv("BACKGROUND_STUDIO_MAX_JOBS", "7")
    monkeypatch.setenv("BACKGROUND_STUDIO_TERMINAL_REGISTRY_MAX", "123")
    monkeypatch.setenv("BACKGROUND_STUDIO_RUNPOD_CANVAS_SIZE", "2048")
    overridden = Settings.from_env()
    assert overridden.max_jobs == 7
    assert overridden.terminal_registry_max == 123
    assert overridden.runpod_canvas_size == 2048


def test_decode_upload_transposes_exif_and_clears_info():
    image = Image.new("RGB", (2, 3), (10, 20, 30))
    exif = Image.Exif()
    exif[274] = 6
    stream = io.BytesIO()
    image.save(
        stream,
        format="JPEG",
        exif=exif,
        icc_profile=b"test-profile",
    )

    decoded = decode_upload(
        stream.getvalue(),
        max_pixels=100,
    )

    assert decoded.mode == "RGB"
    assert decoded.size == (3, 2)
    assert decoded.info == {}


def test_upload_validation_and_byte_limit(
    app_factory,
):
    _, client, fake = app_factory(
        max_upload_bytes=20
    )

    too_large = upload(
        client,
        b"x" * 21,
    )
    assert too_large.status_code == 413

    invalid = upload(
        client,
        b"not an image",
    )
    assert invalid.status_code == 415
    assert fake.calls == 0


def test_rejects_animated_and_excess_pixels(
    app_factory,
):
    _, client, _ = app_factory(
        max_pixels=8
    )

    oversized = upload(
        client,
        image_bytes(size=(3, 3)),
    )
    assert oversized.status_code == 415

    frames = [
        Image.new(
            "RGB",
            (2, 2),
            "red",
        ),
        Image.new(
            "RGB",
            (2, 2),
            "blue",
        ),
    ]
    stream = io.BytesIO()
    frames[0].save(
        stream,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=50,
        loop=0,
    )

    animated = upload(
        client,
        stream.getvalue(),
        "animated.webp",
        "image/webp",
    )
    assert animated.status_code == 415


def test_exif_orientation_is_applied_before_removal(
    app_factory,
):
    exif = Image.Exif()
    exif[274] = 6

    _, client, fake = app_factory()

    response = upload(
        client,
        image_bytes(
            "JPEG",
            (2, 3),
            exif=exif,
        ),
        "rotated.jpg",
        "image/jpeg",
    )

    assert response.status_code == 201
    assert response.json()["width"] == 3
    assert response.json()["height"] == 2
    assert fake.sizes == [(3, 2)]


def test_accepts_jpeg_mpo_container_as_jpg(
    app_factory,
):
    frames = [
        Image.new("RGB", (3, 2), "blue"),
        Image.new("RGB", (3, 2), "red"),
    ]
    stream = io.BytesIO()
    frames[0].save(
        stream,
        format="MPO",
        save_all=True,
        append_images=frames[1:],
    )

    _, client, fake = app_factory()
    response = upload(
        client,
        stream.getvalue(),
        "iphone.jpg",
        "image/jpeg",
    )

    assert response.status_code == 201
    assert response.json()["width"] == 3
    assert response.json()["height"] == 2
    assert fake.sizes == [(3, 2)]


def test_mask_is_reused_for_reversible_processing(
    app_factory,
):
    _, client, fake = app_factory(
        FakeRemover(128)
    )

    created = upload(
        client,
        image_bytes(),
    )
    job_id = created.json()["id"]

    first = client.get(
        f"/api/jobs/{job_id}/preview"
        "?threshold=0"
        "&feather=0"
        "&background=transparent"
    )
    second = client.get(
        f"/api/jobs/{job_id}/preview"
        "?threshold=0.75"
        "&feather=2"
        "&background=%23ffffff"
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert fake.calls == 1

    first_image = Image.open(
        io.BytesIO(first.content)
    ).convert("RGBA")

    assert (
        first_image.getpixel((0, 0))[3]
        == 128
    )


def test_composition_and_full_resolution_exports(
    app_factory,
):
    _, client, _ = app_factory(
        FakeRemover(0)
    )

    created = upload(
        client,
        image_bytes(
            size=(7, 5),
            color=(250, 0, 0),
        ),
    )
    job_id = created.json()["id"]

    transparent = client.get(
        f"/api/jobs/{job_id}/export"
        "?background=transparent"
        "&format=png"
    )
    transparent_image = Image.open(
        io.BytesIO(transparent.content)
    ).convert("RGBA")

    assert transparent.status_code == 200
    assert transparent_image.size == (7, 5)
    assert (
        transparent_image.getpixel((2, 2))[3]
        == 0
    )

    solid = client.get(
        f"/api/jobs/{job_id}/export"
        "?background=%2300ff00"
        "&format=png"
    )
    solid_image = Image.open(
        io.BytesIO(solid.content)
    ).convert("RGB")

    assert (
        solid_image.getpixel((2, 2))
        == (0, 255, 0)
    )

    jpeg = client.get(
        f"/api/jobs/{job_id}/export"
        "?background=%23ffffff"
        "&format=jpeg"
    )

    assert jpeg.status_code == 200
    assert (
        jpeg.headers["content-type"]
        == "image/jpeg"
    )
    assert (
        Image.open(
            io.BytesIO(jpeg.content)
        ).size
        == (7, 5)
    )

    invalid = client.get(
        f"/api/jobs/{job_id}/export"
        "?background=transparent"
        "&format=jpeg"
    )
    assert invalid.status_code == 422


def test_manual_strokes_remove_restore_and_order(
    app_factory,
):
    _, client, _ = app_factory(
        FakeRemover(128)
    )

    job_id = upload(
        client,
        image_bytes(size=(40, 40)),
    ).json()["id"]

    removed = append_stroke(
        client,
        job_id,
        "remove",
    )
    assert removed.status_code == 200
    assert removed.json() == {
        "revision": 1,
        "count": 1,
    }

    remove_export = client.get(
        f"/api/jobs/{job_id}/export"
        "?background=transparent"
        "&format=png"
    )
    assert remove_export.status_code == 200
    assert center_alpha(remove_export) <= 5

    restored = append_stroke(
        client,
        job_id,
        "restore",
    )
    assert restored.status_code == 200
    assert restored.json() == {
        "revision": 2,
        "count": 2,
    }

    restore_export = client.get(
        f"/api/jobs/{job_id}/export"
        "?background=transparent"
        "&format=png"
    )
    assert center_alpha(restore_export) >= 250

    reset = client.delete(
        f"/api/jobs/{job_id}/strokes"
    )
    assert reset.json() == {
        "revision": 3,
        "count": 0,
    }

    append_stroke(
        client,
        job_id,
        "restore",
    )
    append_stroke(
        client,
        job_id,
        "remove",
    )

    reversed_order = client.get(
        f"/api/jobs/{job_id}/export"
        "?background=transparent"
        "&format=png"
    )
    assert center_alpha(reversed_order) <= 5


def test_remove_brush_hugs_subject_edge_and_clears_background(
    app_factory,
):
    _, client, _ = app_factory(
        FakeRemover(255)
    )

    job_id = upload(
        client,
        split_image_bytes(
            subject_color=(55, 70, 35),
            background_color=(240, 238, 228),
        ),
    ).json()["id"]

    removed = append_stroke(
        client,
        job_id,
        "remove",
        radius=0.08,
        points=[
            [0.65, 0.30],
            [0.65, 0.70],
        ],
    )
    assert removed.status_code == 200

    exported = client.get(
        f"/api/jobs/{job_id}/export"
        "?background=transparent"
        "&format=png"
    )
    alpha = response_image(
        exported
    ).getchannel("A")

    assert alpha.getpixel((19, 20)) >= 250
    assert alpha.getpixel((21, 20)) <= 5
    assert alpha.getpixel((30, 20)) <= 5


def test_remove_broad_stroke_protects_subject_and_clears_background(
    app_factory,
):
    _, client, _ = app_factory(
        FakeRemover(255)
    )

    job_id = upload(
        client,
        split_image_bytes(
            subject_color=(15, 15, 15),
            background_color=(220, 220, 215),
        ),
    ).json()["id"]

    removed = append_stroke(
        client,
        job_id,
        "remove",
        radius=0.22,
        softness=0.35,
        points=[
            [0.58, 0.20],
            [0.58, 0.80],
        ],
    )
    assert removed.status_code == 200

    exported = client.get(
        f"/api/jobs/{job_id}/export"
        "?background=transparent"
        "&format=png"
    )
    alpha = response_image(
        exported
    ).getchannel("A")

    assert all(
        alpha.getpixel((x, y)) >= 250
        for x in range(4, 18)
        for y in range(8, 32)
    )
    assert all(
        alpha.getpixel((x, 20)) <= 5
        for x in range(22, 36)
    )


def test_remove_high_resolution_stroke_clears_fragmented_background(
    app_factory,
):
    _, client, _ = app_factory(
        FakeRemover(255),
        max_upload_bytes=10 * 1024 * 1024,
    )

    job_id = upload(
        client,
        fragmented_background_bytes(),
    ).json()["id"]

    removed = append_stroke(
        client,
        job_id,
        "remove",
        radius=0.18,
        softness=0.35,
        points=[
            [0.70, 0.20],
            [0.70, 0.80],
        ],
    )
    assert removed.status_code == 200

    exported = client.get(
        f"/api/jobs/{job_id}/export"
        "?background=transparent"
        "&format=png"
    )
    alpha = response_image(
        exported
    ).getchannel("A")

    assert all(
        alpha.getpixel((x, y)) >= 250
        for x in range(40, 260)
        for y in range(80, 560)
    )
    assert all(
        alpha.getpixel((x, y)) <= 5
        for x in range(340, 560)
        for y in range(80, 560)
    )


def test_restore_brush_hugs_contrasting_subject_edge(
    app_factory,
):
    _, client, _ = app_factory(
        FakeRemover(0)
    )

    job_id = upload(
        client,
        split_image_bytes(),
    ).json()["id"]

    restored = append_stroke(
        client,
        job_id,
        "restore",
        radius=0.35,
        points=[
            [0.35, 0.25],
            [0.35, 0.75],
        ],
    )
    assert restored.status_code == 200

    rendered = [
        client.get(
            f"/api/jobs/{job_id}/preview"
            "?background=transparent"
        ),
        client.get(
            f"/api/jobs/{job_id}/export"
            "?background=transparent"
            "&format=png"
        ),
    ]

    for response in rendered:
        assert response.status_code == 200
        alpha = response_image(
            response
        ).getchannel("A")
        assert alpha.getpixel((15, 20)) >= 250
        assert alpha.getpixel((24, 20)) <= 5


def test_restore_brush_fills_across_internal_subject_texture(
    app_factory,
):
    _, client, _ = app_factory(
        FakeRemover(0)
    )

    job_id = upload(
        client,
        split_image_bytes(textured=True),
    ).json()["id"]

    restored = append_stroke(
        client,
        job_id,
        "restore",
        radius=0.08,
        points=[
            [0.35, 0.30],
            [0.35, 0.70],
        ],
    )
    assert restored.status_code == 200

    exported = client.get(
        f"/api/jobs/{job_id}/export"
        "?background=transparent"
        "&format=png"
    )
    alpha = response_image(
        exported
    ).getchannel("A")

    assert alpha.getpixel((8, 20)) >= 250
    assert alpha.getpixel((10, 20)) >= 250
    assert alpha.getpixel((15, 20)) >= 250
    assert alpha.getpixel((24, 20)) <= 5


def test_restore_broad_stroke_keeps_subject_solid_without_texture_islands(
    app_factory,
):
    _, client, _ = app_factory(
        FakeRemover(0)
    )

    job_id = upload(
        client,
        split_image_bytes(
            textured=True,
            subject_color=(25, 25, 25),
            background_color=(20, 60, 220),
            texture_color=(245, 245, 240),
        ),
    ).json()["id"]

    restored = append_stroke(
        client,
        job_id,
        "restore",
        radius=0.22,
        softness=0.35,
        points=[
            [0.35, 0.20],
            [0.35, 0.80],
        ],
    )
    assert restored.status_code == 200

    exported = client.get(
        f"/api/jobs/{job_id}/export"
        "?background=transparent"
        "&format=png"
    )
    alpha = response_image(
        exported
    ).getchannel("A")

    assert all(
        alpha.getpixel((x, y)) >= 250
        for x in range(4, 18)
        for y in range(8, 32)
    )
    assert all(
        alpha.getpixel((x, 20)) <= 5
        for x in range(24, 36)
    )


def test_restore_brush_fills_across_high_contrast_shirt_print(
    app_factory,
):
    _, client, _ = app_factory(
        FakeRemover(0)
    )

    job_id = upload(
        client,
        split_image_bytes(
            textured=True,
            subject_color=(25, 25, 25),
            background_color=(20, 60, 220),
            texture_color=(245, 245, 240),
        ),
    ).json()["id"]

    append_stroke(
        client,
        job_id,
        "restore",
        radius=0.35,
        points=[
            [0.35, 0.25],
            [0.35, 0.75],
        ],
    )
    exported = client.get(
        f"/api/jobs/{job_id}/export"
        "?background=transparent"
        "&format=png"
    )
    alpha = response_image(
        exported
    ).getchannel("A")

    assert alpha.getpixel((8, 20)) >= 250
    assert alpha.getpixel((19, 20)) >= 250
    assert alpha.getpixel((21, 20)) <= 5


def test_restore_brush_follows_a_low_contrast_subject_edge(
    app_factory,
):
    _, client, _ = app_factory(
        FakeRemover(0)
    )

    job_id = upload(
        client,
        split_image_bytes(
            subject_color=(120, 80, 60),
            background_color=(155, 115, 95),
        ),
    ).json()["id"]

    append_stroke(
        client,
        job_id,
        "restore",
        radius=0.35,
        points=[
            [0.35, 0.25],
            [0.35, 0.75],
        ],
    )
    exported = client.get(
        f"/api/jobs/{job_id}/export"
        "?background=transparent"
        "&format=png"
    )
    alpha = response_image(
        exported
    ).getchannel("A")

    assert alpha.getpixel((19, 20)) >= 250
    assert alpha.getpixel((21, 20)) <= 5


def test_restore_brush_assists_beyond_the_literal_stroke(
    app_factory,
):
    _, client, _ = app_factory(
        FakeRemover(0)
    )

    job_id = upload(
        client,
        split_image_bytes(),
    ).json()["id"]

    append_stroke(
        client,
        job_id,
        "restore",
        radius=0.08,
        points=[
            [0.35, 0.30],
            [0.35, 0.70],
        ],
    )
    exported = client.get(
        f"/api/jobs/{job_id}/export"
        "?background=transparent"
        "&format=png"
    )
    alpha = response_image(
        exported
    ).getchannel("A")

    assert alpha.getpixel((8, 20)) >= 240
    assert alpha.getpixel((19, 20)) >= 240
    assert alpha.getpixel((21, 20)) <= 5


def test_restore_brush_does_not_assist_without_an_edge(
    app_factory,
):
    _, client, _ = app_factory(
        FakeRemover(0)
    )

    job_id = upload(
        client,
        image_bytes(
            size=(40, 40),
            color=(120, 80, 60),
        ),
    ).json()["id"]

    append_stroke(
        client,
        job_id,
        "restore",
        radius=0.08,
        points=[
            [0.35, 0.30],
            [0.35, 0.70],
        ],
    )
    exported = client.get(
        f"/api/jobs/{job_id}/export"
        "?background=transparent"
        "&format=png"
    )
    alpha = response_image(
        exported
    ).getchannel("A")

    assert alpha.getpixel((14, 20)) >= 250
    assert alpha.getpixel((8, 20)) <= 5


def test_restore_brush_rejects_white_background_and_closes_small_holes(
    app_factory,
):
    _, client, _ = app_factory(
        FakeRemover(0)
    )

    job_id = upload(
        client,
        shirt_on_white_bytes(),
    ).json()["id"]

    append_stroke(
        client,
        job_id,
        "restore",
        radius=0.08,
        points=[
            [0.35, 0.30],
            [0.35, 0.70],
        ],
    )
    exported = client.get(
        f"/api/jobs/{job_id}/export"
        "?background=transparent"
        "&format=png"
    )
    alpha = response_image(
        exported
    ).getchannel("A")

    assert alpha.getpixel((10, 20)) >= 250
    assert alpha.getpixel((19, 20)) >= 250
    assert alpha.getpixel((21, 20)) <= 5


def test_restore_brush_falls_back_to_solid_manual_paint_when_ambiguous(
    app_factory,
):
    _, client, _ = app_factory(
        PartialForegroundRemover()
    )

    job_id = upload(
        client,
        split_image_bytes(
            subject_color=(220, 220, 215),
            background_color=(235, 235, 230),
        ),
    ).json()["id"]

    append_stroke(
        client,
        job_id,
        "restore",
        radius=0.08,
        softness=0.8,
        points=[
            [0.40, 0.30],
            [0.40, 0.70],
        ],
    )
    exported = client.get(
        f"/api/jobs/{job_id}/export"
        "?background=transparent"
        "&format=png"
    )
    alpha = response_image(
        exported
    ).getchannel("A")

    assert alpha.getpixel((18, 20)) >= 250
    assert alpha.getpixel((21, 20)) <= 5


def test_manual_stroke_undo_and_reset(
    app_factory,
):
    _, client, _ = app_factory(
        FakeRemover(255)
    )

    job_id = upload(
        client,
        image_bytes(size=(40, 40)),
    ).json()["id"]

    append_stroke(
        client,
        job_id,
        "remove",
    )

    undo = client.delete(
        f"/api/jobs/{job_id}/strokes/last"
    )
    assert undo.status_code == 200
    assert undo.json() == {
        "revision": 2,
        "count": 0,
    }

    after_undo = client.get(
        f"/api/jobs/{job_id}/export"
        "?background=transparent"
        "&format=png"
    )
    assert center_alpha(after_undo) == 255

    empty_undo = client.delete(
        f"/api/jobs/{job_id}/strokes/last"
    )
    assert empty_undo.json() == {
        "revision": 2,
        "count": 0,
    }

    append_stroke(
        client,
        job_id,
        "remove",
    )
    append_stroke(
        client,
        job_id,
        "restore",
    )

    reset = client.delete(
        f"/api/jobs/{job_id}/strokes"
    )
    assert reset.status_code == 200
    assert reset.json() == {
        "revision": 5,
        "count": 0,
    }

    after_reset = client.get(
        f"/api/jobs/{job_id}/export"
        "?background=transparent"
        "&format=png"
    )
    assert center_alpha(after_reset) == 255

    empty_reset = client.delete(
        f"/api/jobs/{job_id}/strokes"
    )
    assert empty_reset.json() == {
        "revision": 5,
        "count": 0,
    }


def test_manual_stroke_validation_and_missing_jobs(
    app_factory,
):
    _, client, _ = app_factory()

    job_id = upload(
        client,
        image_bytes(),
    ).json()["id"]

    valid = {
        "mode": "remove",
        "radius": 0.1,
        "softness": 0.5,
        "points": [
            [0.0, 0.0],
            [1.0, 1.0],
        ],
    }
    invalid_payloads = [
        {
            **valid,
            "mode": "paint",
        },
        {
            **valid,
            "radius": 0,
        },
        {
            **valid,
            "radius": 1.01,
        },
        {
            **valid,
            "softness": -0.01,
        },
        {
            **valid,
            "softness": 1.01,
        },
        {
            **valid,
            "points": [[0.5, 0.5]],
        },
        {
            **valid,
            "points": [
                [0.5, 0.5]
            ] * 2049,
        },
        {
            **valid,
            "points": [
                [-0.01, 0.5],
                [0.5, 0.5],
            ],
        },
        {
            **valid,
            "points": [
                [0.5],
                [0.5, 0.5],
            ],
        },
        {
            **valid,
            "radius": "0.1",
        },
        {
            **valid,
            "unexpected": True,
        },
    ]

    for payload in invalid_payloads:
        response = client.post(
            f"/api/jobs/{job_id}/strokes",
            json=payload,
        )
        assert response.status_code == 422

    missing = "0" * 32
    missing_append = client.post(
        f"/api/jobs/{missing}/strokes",
        json=valid,
    )
    missing_undo = client.delete(
        f"/api/jobs/{missing}/strokes/last"
    )
    missing_reset = client.delete(
        f"/api/jobs/{missing}/strokes"
    )

    assert missing_append.status_code == 404
    assert missing_undo.status_code == 404
    assert missing_reset.status_code == 404


def test_manual_strokes_reuse_immutable_raw_mask_and_export(
    app_factory,
):
    app, client, fake = app_factory(
        FakeRemover(255),
        preview_max_side=16,
    )

    job_id = upload(
        client,
        image_bytes(size=(64, 40)),
    ).json()["id"]
    job = app.state.store._jobs[job_id]
    raw_mask_before = job.mask_path.read_bytes()

    appended = append_stroke(
        client,
        job_id,
        "remove",
        radius=0.2,
        softness=0.5,
    )
    assert appended.status_code == 200

    preview = client.get(
        f"/api/jobs/{job_id}/preview"
        "?threshold=0"
        "&feather=0"
        "&background=transparent"
    )
    exported = client.get(
        f"/api/jobs/{job_id}/export"
        "?threshold=0"
        "&feather=0"
        "&background=transparent"
        "&format=png"
    )

    preview_image = response_image(preview)
    export_image = response_image(exported)

    assert preview.status_code == 200
    assert exported.status_code == 200
    assert preview_image.size == (16, 10)
    assert export_image.size == (64, 40)
    assert center_alpha(preview) <= 5
    assert center_alpha(exported) <= 5
    assert job.mask_path.read_bytes() == raw_mask_before
    assert fake.calls == 1

    _, raw_mask = app.state.store.read_images(
        job_id
    )
    assert raw_mask.getpixel((32, 20)) == 255


def test_idempotent_client_job_id_and_invalid_ids(app_factory):
    app, client, fake = app_factory()
    job_id = "0123456789abcdef0123456789abcdef"
    files = {"file": ("photo.png", image_bytes(), "image/png")}
    first = client.post("/api/jobs", data={"job_id": job_id}, files=files)
    repeat = client.post("/api/jobs", data={"job_id": job_id}, files=files)
    assert first.status_code == repeat.status_code == 201
    assert first.json() == repeat.json()
    assert fake.calls == 1
    status = client.get(f"/api/jobs/{job_id}")
    assert status.status_code == 200
    assert status.json() == first.json()
    assert client.post("/api/jobs", data={"job_id": "../escape"}, files=files).status_code == 422
    assert list(app.state.store.root.glob("*escape*")) == []


def test_get_unknown_job_is_404(app_factory):
    _, client, _ = app_factory()
    job_id = "0" * 32
    response = client.get(f"/api/jobs/{job_id}")
    assert response.status_code == 404
    assert response.json() == {"id": job_id, "state": "unknown"}


def test_cancel_unknown_tombstones_id_before_delayed_create(app_factory):
    _, client, fake = app_factory()
    job_id = "9" * 32

    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 204
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 204
    created = client.post(
        "/api/jobs",
        data={"job_id": job_id},
        files={"file": ("photo.png", image_bytes(), "image/png")},
    )

    assert created.status_code == 410
    assert created.json()["detail"]["state"] == "tombstoned"
    assert fake.calls == 0


def test_cancel_creating_job_is_pending_until_worker_cleanup(app_factory):
    entered = threading.Event()
    release = threading.Event()

    class DelayedRemover(FakeRemover):
        def remove(self, image):
            entered.set()
            assert release.wait(2)
            return super().remove(image)

    app, client, _ = app_factory(DelayedRemover())
    job_id = "a" * 32

    def post():
        return client.post(
            "/api/jobs",
            data={"job_id": job_id},
            files={"file": ("photo.png", image_bytes(), "image/png")},
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(post)
        try:
            assert entered.wait(1)
            first = client.post(f"/api/jobs/{job_id}/cancel")
            repeated = client.post(f"/api/jobs/{job_id}/cancel")
            assert first.status_code == repeated.status_code == 202
            assert first.json() == repeated.json() == {
                "id": job_id,
                "state": "cleanup_pending",
            }
        finally:
            release.set()
        response = pending.result(timeout=2)

    assert response.status_code == 410
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 204
    assert job_id not in app.state.store._jobs


def test_cancel_live_job_cleans_and_repeats_as_204(app_factory):
    app, client, _ = app_factory()
    job_id = upload(client, image_bytes()).json()["id"]
    directory = app.state.store._jobs[job_id].directory

    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 204
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 204
    assert not directory.exists()
    terminal = client.get(f"/api/jobs/{job_id}")
    assert terminal.status_code == 410
    assert terminal.json() == {"id": job_id, "state": "tombstoned"}


def test_cancel_waits_for_active_render_lease(app_factory, monkeypatch):
    app, client, _ = app_factory()
    job_id = upload(client, image_bytes()).json()["id"]
    directory = app.state.store._jobs[job_id].directory
    entered = threading.Event()
    release = threading.Event()
    real_release_render = app.state.store.release_render

    def delayed_release_render(lease_id):
        entered.set()
        assert release.wait(2)
        return real_release_render(lease_id)

    monkeypatch.setattr(app.state.store, "release_render", delayed_release_render)
    concurrent_client = TestClient(app)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            rendering = pool.submit(client.get, f"/api/jobs/{job_id}/preview")
            try:
                assert entered.wait(1)
                for _ in range(2):
                    cancelled = concurrent_client.post(f"/api/jobs/{job_id}/cancel")
                    assert cancelled.status_code == 202
                    assert cancelled.headers["retry-after"] == "1"
                    assert cancelled.json() == {"id": job_id, "state": "cleanup_pending"}
                    assert directory.exists()
            finally:
                release.set()
            assert rendering.result(timeout=2).status_code == 200
    finally:
        concurrent_client.close()

    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 204
    assert not directory.exists()


def test_cancel_retries_only_this_jobs_quarantines(app_factory, monkeypatch):
    app, client, _ = app_factory()
    first_id = upload(client, image_bytes()).json()["id"]
    second_id = upload(client, image_bytes()).json()["id"]
    first_directory = app.state.store._jobs[first_id].directory
    second_directory = app.state.store._jobs[second_id].directory
    targets = {first_directory, second_directory}
    failed_once = set()

    import app.store as store_module
    real_rmtree = store_module.shutil.rmtree

    def flaky(path, *args, **kwargs):
        if path in targets and path not in failed_once:
            failed_once.add(path)
            raise OSError("busy")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(store_module.shutil, "rmtree", flaky)
    assert client.post(f"/api/jobs/{first_id}/cancel").status_code == 202
    assert client.post(f"/api/jobs/{second_id}/cancel").status_code == 202
    assert first_directory.exists() and second_directory.exists()

    assert client.post(f"/api/jobs/{first_id}/cancel").status_code == 204
    assert not first_directory.exists() and second_directory.exists()
    assert client.post(f"/api/jobs/{first_id}/cancel").status_code == 204
    assert client.post(f"/api/jobs/{second_id}/cancel").status_code == 204
    assert not second_directory.exists()


def test_concurrent_cancel_cannot_observe_quarantine_handoff_gap(app_factory, monkeypatch):
    app, client, _ = app_factory()
    job_id = upload(client, image_bytes()).json()["id"]
    store = app.state.store
    directory = store._jobs[job_id].directory
    before = store.stats()[1]
    scanning = threading.Event()
    release = threading.Event()

    import app.store as store_module
    real_rmtree = store_module.shutil.rmtree
    real_directory_bytes = store._directory_bytes

    def fail_target(path, *args, **kwargs):
        if path == directory:
            raise OSError("busy")
        return real_rmtree(path, *args, **kwargs)

    def paused_scan(path):
        if path == directory:
            scanning.set()
            assert release.wait(2)
        return real_directory_bytes(path)

    monkeypatch.setattr(store_module.shutil, "rmtree", fail_target)
    monkeypatch.setattr(store, "_directory_bytes", paused_scan)
    concurrent_client = TestClient(app)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(client.post, f"/api/jobs/{job_id}/cancel")
            try:
                assert scanning.wait(1)
                repeated = concurrent_client.post(f"/api/jobs/{job_id}/cancel")
                assert repeated.status_code == 202
                assert store.stats()[1] == before
            finally:
                release.set()
            assert first.result(timeout=2).status_code == 202
    finally:
        concurrent_client.close()

    monkeypatch.setattr(store_module.shutil, "rmtree", real_rmtree)
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 204
    assert store.stats()[1] == 0


def test_cancel_registry_full_is_machine_readable(app_factory):
    _, client, _ = app_factory(terminal_registry_max=1)
    assert client.post(f"/api/jobs/{'b' * 32}/cancel").status_code == 204
    full = client.post(f"/api/jobs/{'c' * 32}/cancel")
    assert full.status_code == 507
    assert full.json()["cause"] == "terminal_registry"


def test_live_capacity_507_keeps_detail_and_adds_cause(app_factory):
    _, client, _ = app_factory(max_jobs=1)
    upload(client, image_bytes())
    response = client.post(
        "/api/jobs",
        data={"job_id": "d" * 32},
        files={"file": ("photo.png", image_bytes(), "image/png")},
    )
    assert response.status_code == 507
    assert response.json() == {
        "detail": "The job limit has been reached. Delete a job and try again.",
        "cause": "live_capacity",
    }


def test_disk_and_memory_capacity_causes_are_machine_readable(app_factory):
    _, disk_client, _ = app_factory(disk_quota_bytes=1)
    disk = upload(disk_client, image_bytes())
    assert disk.status_code == 507
    assert disk.json()["cause"] == "disk_quota"

    _, memory_client, _ = app_factory(memory_quota_bytes=1)
    memory = upload(memory_client, image_bytes())
    assert memory.status_code == 507
    assert memory.json()["cause"] == "memory_quota"


def test_capacity_causes_do_not_depend_on_human_messages(app_factory, monkeypatch):
    app, client, _ = app_factory()

    def opaque_body_failure(_declared):
        raise StoreCapacityError("opaque body failure", "memory_quota")

    monkeypatch.setattr(app.state.store, "reserve_body", opaque_body_failure)
    middleware = upload(client, image_bytes())
    assert middleware.status_code == 507
    assert middleware.json() == {
        "detail": "opaque body failure",
        "cause": "memory_quota",
    }

    app2, client2, _ = app_factory()

    def opaque_generation_failure(*_args, **_kwargs):
        raise StoreCapacityError("opaque generation failure", "disk_quota")

    monkeypatch.setattr(app2.state.store, "reserve_resources", opaque_generation_failure)
    generation = upload(client2, image_bytes())
    assert generation.status_code == 507
    assert generation.json() == {
        "detail": "opaque generation failure",
        "cause": "disk_quota",
    }


def test_concurrent_duplicate_posts_share_one_terminal_result(app_factory):
    entered = threading.Event()
    release = threading.Event()

    class DelayedRemover(FakeRemover):
        def remove(self, image):
            entered.set()
            assert release.wait(2)
            return super().remove(image)

    _, client, fake = app_factory(DelayedRemover())
    job_id = "1234567890abcdef1234567890abcdef"

    def post():
        return client.post(
            "/api/jobs",
            data={"job_id": job_id},
            files={"file": ("photo.png", image_bytes(), "image/png")},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(post)
        assert entered.wait(1)
        second = pool.submit(post)
        time.sleep(0.05)
        release.set()
        first_response = first.result(timeout=2)
        second_response = second.result(timeout=2)

    assert first_response.status_code == second_response.status_code == 201
    assert first_response.json() == second_response.json()
    assert fake.calls == 1


def test_public_posts_serialize_inference_across_failure(app_factory):
    class OverlapProbeRemover(FakeRemover):
        def __init__(self):
            super().__init__()
            self._state_lock = threading.Lock()
            self.entered = threading.Event()
            self.release = threading.Event()
            self.active = 0
            self.max_active = 0

        def remove(self, image):
            with self._state_lock:
                self.calls += 1
                call_number = self.calls
                self.sizes.append(image.size)
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            try:
                if call_number == 1:
                    self.entered.set()
                assert self.release.wait(2)
                if call_number == 2:
                    raise RuntimeError("second inference failed")
                return Image.new("L", image.size, self.value)
            finally:
                with self._state_lock:
                    self.active -= 1

    probe = OverlapProbeRemover()
    _, client, _ = app_factory(probe)
    first_id = "6" * 32
    second_id = "7" * 32

    def post(job_id):
        return client.post(
            "/api/jobs",
            data={"job_id": job_id},
            files={"file": ("photo.png", image_bytes(), "image/png")},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(post, first_id)
        assert probe.entered.wait(1)
        second = pool.submit(post, second_id)
        try:
            deadline = time.monotonic() + 1
            while True:
                creating = client.get(f"/api/jobs/{second_id}")
                if creating.status_code == 202:
                    break
                assert creating.status_code == 404
                assert time.monotonic() < deadline
                time.sleep(0.01)
        finally:
            probe.release.set()
        first_response = first.result(timeout=2)
        second_response = second.result(timeout=2)

    assert first_response.status_code == 201
    assert second_response.status_code == 500
    assert probe.calls == 2
    assert probe.max_active == 1
    failed = client.get(f"/api/jobs/{second_id}")
    assert failed.status_code == 410
    assert failed.json() == {"id": second_id, "state": "failed"}


def test_delete_tombstones_creating_job_and_prevents_late_publish(app_factory):
    entered = threading.Event()
    release = threading.Event()

    class DelayedRemover(FakeRemover):
        def remove(self, image):
            entered.set()
            assert release.wait(2)
            return super().remove(image)

    app, client, _ = app_factory(DelayedRemover())
    job_id = "abcdef1234567890abcdef1234567890"

    def post():
        return client.post(
            "/api/jobs",
            data={"job_id": job_id},
            files={"file": ("photo.png", image_bytes(), "image/png")},
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(post)
        assert entered.wait(1)
        creating = client.get(f"/api/jobs/{job_id}")
        assert creating.status_code == 202
        assert creating.json() == {"id": job_id, "state": "creating"}
        assert creating.headers["retry-after"] == "1"
        assert client.delete(f"/api/jobs/{job_id}").status_code == 204
        release.set()
        response = pending.result(timeout=2)

    assert response.status_code == 410
    status = client.get(f"/api/jobs/{job_id}")
    assert status.status_code == 410
    assert status.json() == {"id": job_id, "state": "tombstoned"}
    assert job_id not in app.state.store._jobs
    assert not (app.state.store.root / f"job-{job_id}").exists()


def test_touch_advances_live_job_without_rendering_and_maps_lifecycle(
    app_factory,
    monkeypatch,
):
    app, client, _ = app_factory()
    job_id = upload(client, image_bytes()).json()["id"]
    store = app.state.store
    with store._lock:
        before = store._jobs[job_id].last_access

    def unexpected_image_open(*args, **kwargs):
        raise AssertionError("touch must not open job images")

    with monkeypatch.context() as patch_context:
        patch_context.setattr(Image, "open", unexpected_image_open)
        time.sleep(0.01)
        touched = client.post(f"/api/jobs/{job_id}/touch")
    assert touched.status_code == 204
    assert touched.content == b""
    with store._lock:
        assert store._jobs[job_id].last_access > before

    unknown_id = "8" * 32
    unknown = client.post(f"/api/jobs/{unknown_id}/touch")
    assert unknown.status_code == 404
    assert unknown.json() == {"id": unknown_id, "state": "unknown"}

    assert client.delete(f"/api/jobs/{job_id}").status_code == 204
    terminal = client.post(f"/api/jobs/{job_id}/touch")
    assert terminal.status_code == 410
    assert terminal.json() == {"id": job_id, "state": "tombstoned"}


def test_delete_failure_keeps_accounting_and_cleanup_retries(app_factory, monkeypatch):
    app, client, _ = app_factory(job_ttl_seconds=1)
    job_id = upload(client, image_bytes()).json()["id"]
    job = app.state.store._jobs[job_id]
    before = app.state.store.stats()
    import app.store as store_module
    real_rmtree = store_module.shutil.rmtree
    attempts = 0
    def flaky(path, *args, **kwargs):
        nonlocal attempts
        if path == job.directory and attempts == 0:
            attempts += 1
            raise OSError("busy")
        return real_rmtree(path, *args, **kwargs)
    monkeypatch.setattr(store_module.shutil, "rmtree", flaky)
    assert client.delete(f"/api/jobs/{job_id}").status_code == 500
    assert app.state.store.stats() == (0, before[1])
    assert job_id not in app.state.store._jobs and job.directory.exists()
    assert app.state.store.lifecycle(job_id).state == "failed"
    assert app.state.store.cleanup_expired() == 1
    assert job_id not in app.state.store._jobs and not job.directory.exists()


def test_partial_create_cleanup_failure_is_tracked_and_accounted(app_factory, monkeypatch):
    app, _, _ = app_factory()
    store = app.state.store
    job_id = "fedcba0987654321fedcba0987654321"
    _, owner, _, generation = store.reserve(job_id, 0)
    assert owner and generation is not None
    original = Image.new("RGB", (8, 6), "red")
    mask = Image.new("L", (8, 6), 255)
    reserved, _ = store.reserve_resources(job_id, generation, 100, 8, 6)
    real_save = store._save_private
    saves = 0

    def fail_second_save(image, path):
        nonlocal saves
        saves += 1
        if saves == 2:
            raise OSError("write failed")
        return real_save(image, path)

    import app.store as store_module
    real_rmtree = store_module.shutil.rmtree
    directory = store.root / f"job-{job_id}-{generation}"

    def refuse_cleanup(path, *args, **kwargs):
        if path == directory:
            raise OSError("privacy cleanup failed")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(store, "_save_private", fail_second_save)
    monkeypatch.setattr(store_module.shutil, "rmtree", refuse_cleanup)
    from app.store import StoreCreationError

    with pytest.raises(StoreCreationError, match="cleanup remains tracked") as caught:
        store.create(original, mask, job_id, generation)

    assert caught.value.classification == "cleanup"
    assert generation not in store._generation_leases
    assert store._reserved_memory_bytes == 0
    lifecycle = store.lifecycle(job_id)
    assert lifecycle is not None and lifecycle.state == "failed"
    quarantine = next(iter(store._quarantines.values()))
    assert quarantine.directory == directory and 0 < quarantine.disk_bytes <= reserved
    assert store.finalize_creation(job_id, generation, str(caught.value)) is False
    assert store.stats() == (0, quarantine.disk_bytes)

    monkeypatch.setattr(store_module.shutil, "rmtree", real_rmtree)
    assert store.cleanup_expired() == 1
    assert store.stats() == (0, 0)
    assert not directory.exists()


@pytest.mark.parametrize("operation", ["delete", "cleanup", "shutdown"])
def test_verified_absent_live_directory_clears_accounting(app_factory, operation):
    app, client, _ = app_factory(job_ttl_seconds=1)
    store = app.state.store
    job_id = upload(client, image_bytes()).json()["id"]
    job = store._jobs[job_id]
    import shutil
    shutil.rmtree(job.directory)

    if operation == "delete":
        assert store.delete(job_id) is True
    elif operation == "cleanup":
        job.last_access = time.monotonic() - 2
        assert store.cleanup_expired() == 1
    else:
        store.shutdown()

    assert store.stats() == (0, 0)
    assert job_id not in store._jobs


def test_delete_expiry_and_shutdown_cleanup(
    app_factory,
):
    app, client, _ = app_factory(
        job_ttl_seconds=1
    )

    first = upload(
        client,
        image_bytes(),
    ).json()["id"]

    directory = (
        app.state.store
        ._jobs[first]
        .directory
    )

    assert directory.exists()
    assert (
        client.delete(
            f"/api/jobs/{first}"
        ).status_code
        == 204
    )
    assert not directory.exists()
    assert (
        client.get(
            f"/api/jobs/{first}/original"
        ).status_code
        == 410
    )

    second = upload(
        client,
        image_bytes(),
    ).json()["id"]

    second_job = (
        app.state.store
        ._jobs[second]
    )
    second_job.last_access = (
        time.monotonic() - 2
    )

    assert (
        app.state.store.cleanup_expired()
        == 1
    )
    assert not second_job.directory.exists()


def test_startup_fails_closed_when_stale_storage_cannot_be_removed(app_factory, monkeypatch):
    app, _, _ = app_factory()
    settings = app.state.settings
    stale = settings.temp_root / "job-stale"
    stale.mkdir(mode=0o700)
    store = JobStore(settings)
    import app.store as store_module
    real_rmtree = store_module.shutil.rmtree

    def refuse(path, *args, **kwargs):
        if path == stale:
            raise OSError("busy")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(store_module.shutil, "rmtree", refuse)
    with pytest.raises(StoreDeletionError, match="startup is blocked"):
        store.startup()
    assert stale.exists()


def test_shutdown_surfaces_cleanup_failure_and_retains_accounting(app_factory, monkeypatch):
    app, client, _ = app_factory()
    job_id = upload(client, image_bytes()).json()["id"]
    store = app.state.store
    job = store._jobs[job_id]
    before = store.stats()
    import app.store as store_module
    real_rmtree = store_module.shutil.rmtree

    def refuse(path, *args, **kwargs):
        if path == job.directory:
            raise OSError("busy")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(store_module.shutil, "rmtree", refuse)
    with pytest.raises(StoreDeletionError, match=job_id):
        store.shutdown()
    assert store.stats() == (0, before[1])
    assert job_id not in store._jobs
    assert store.lifecycle(job_id).state == "failed"
    assert job.directory.exists()
    monkeypatch.setattr(store_module.shutil, "rmtree", real_rmtree)
    store.shutdown()
    assert store.stats() == (0, 0)
    assert not job.directory.exists()


def test_terminal_job_id_is_never_reused_after_ttl(app_factory):
    app, _, _ = app_factory(job_ttl_seconds=1)
    store = app.state.store
    job_id = "11111111111111111111111111111111"
    _, owner, lifecycle, generation = store.reserve(job_id, 0)
    assert owner and generation is not None
    assert store.delete(job_id) is True
    assert store.finalize_creation(job_id, generation, "cancelled")

    store._lifecycles[job_id].updated_at = time.monotonic() - store.WAIT_SECONDS - 1
    store.cleanup_expired(time.monotonic())
    _, replacement_owner, retained, replacement_generation = store.reserve(job_id, 0)

    assert not replacement_owner
    assert replacement_generation is None
    assert retained.state == "tombstoned"
    assert job_id not in store._lifecycles
    assert job_id not in store._jobs


def test_cleanup_revalidates_access_after_expired_snapshot(app_factory, monkeypatch):
    app, client, _ = app_factory(job_ttl_seconds=1)
    store = app.state.store
    job_id = upload(client, image_bytes()).json()["id"]
    job = store._jobs[job_id]
    job.last_access = time.monotonic() - 2
    snapshotted = threading.Event()
    accessed = threading.Event()
    real_delete_if_expired = store._delete_if_expired

    def pause_after_snapshot(candidate_id, candidate, current):
        snapshotted.set()
        assert accessed.wait(2)
        return real_delete_if_expired(candidate_id, candidate, current)

    monkeypatch.setattr(store, "_delete_if_expired", pause_after_snapshot)
    with ThreadPoolExecutor(max_workers=1) as pool:
        cleanup = pool.submit(store.cleanup_expired)
        assert snapshotted.wait(1)
        assert store.get(job_id) is job
        accessed.set()
        assert cleanup.result(timeout=2) == 0

    assert store._jobs[job_id] is job
    assert job.directory.exists()


def test_preview_scales_feather_pixels_but_full_render_does_not(monkeypatch):
    import app.main as main_module

    class Store:
        @staticmethod
        def read_render_data(job_id):
            return (
                Image.new("RGB", (100, 50), "red"),
                Image.new("L", (100, 50), 128),
                [],
            )

    feathers = []

    def derive_alpha(mask, threshold, feather):
        feathers.append(feather)
        return mask

    monkeypatch.setattr(main_module, "derive_alpha", derive_alpha)
    monkeypatch.setattr(
        main_module,
        "apply_strokes",
        lambda alpha, strokes, original: alpha,
    )
    monkeypatch.setattr(main_module, "compose", lambda original, alpha, background: original)

    preview = main_module._render(Store(), "job", 0, 10, "transparent", 20)
    exported = main_module._render(Store(), "job", 0, 10, "transparent")

    assert preview.size == (20, 10)
    assert exported.size == (100, 50)
    assert feathers == [2, 10]


def test_unique_creating_requests_atomically_consume_job_capacity(app_factory):
    app, _, _ = app_factory(max_jobs=1)
    store = app.state.store
    _, owner, _, generation = store.reserve("2" * 32, 0)
    assert owner
    with pytest.raises(StoreCapacityError, match="job limit"):
        store.reserve("3" * 32, 0)
    store.finalize_creation("2" * 32, generation, "done")


def test_concurrent_generation_reservations_cannot_overbook_disk(app_factory):
    app, _, _ = app_factory(max_jobs=2, disk_quota_bytes=3000)
    store = app.state.store
    _, _, _, generation_a = store.reserve("4" * 32, 0)
    _, _, _, generation_b = store.reserve("5" * 32, 0)
    store.reserve_resources("4" * 32, generation_a, 100, 8, 6)
    with pytest.raises(StoreCapacityError, match="disk quota"):
        store.reserve_resources("5" * 32, generation_b, 100, 8, 6)
    store.fail_creation("4" * 32, generation_a, "done")
    store.fail_creation("5" * 32, generation_b, "done")
    assert store.stats() == (0, 0)


def test_quarantine_cleanup_never_revives_or_mutates_terminal_id(app_factory, monkeypatch):
    app, _, _ = app_factory(job_ttl_seconds=1)
    store = app.state.store
    job_id = "6" * 32
    _, _, lifecycle, generation = store.reserve(job_id, 0)
    store.reserve_resources(job_id, generation, 100, 8, 6)
    old_dir = store.root / f"job-{job_id}-{generation}"
    old_dir.mkdir(mode=0o700)
    (old_dir / "partial").write_bytes(b"old")
    quarantine = store._quarantine(job_id, generation, old_dir, OSError("old"))
    store.fail_creation(job_id, generation, "old failed")

    import app.store as store_module
    real_rmtree = store_module.shutil.rmtree
    monkeypatch.setattr(store_module.shutil, "rmtree", lambda path, *a, **k: (_ for _ in ()).throw(OSError("busy")) if path == old_dir else real_rmtree(path, *a, **k))
    assert store.cleanup_expired() == 0
    current = store.lifecycle(job_id)
    assert current is not lifecycle
    assert current.state == "failed"
    assert quarantine.id in store._quarantines

    monkeypatch.setattr(store_module.shutil, "rmtree", real_rmtree)
    assert store.cleanup_expired() == 1
    current = store.lifecycle(job_id)
    assert current is not lifecycle
    assert current.state == "failed"
    assert job_id not in store._jobs


def _run_body_limit(messages, headers, limit=10):
    called = False
    sent = []

    async def endpoint(scope, receive, send):
        nonlocal called
        called = True

    middleware = RequestBodyLimitMiddleware(endpoint, limit)

    async def run():
        queue = list(messages)
        async def receive():
            return queue.pop(0)
        async def send(message):
            sent.append(message)
        await middleware({"type": "http", "headers": headers}, receive, send)

    asyncio.run(run())
    return called, sent


def test_request_body_limit_rejects_oversized_content_length_before_endpoint():
    called, sent = _run_body_limit(
        [{"type": "http.request", "body": b"x", "more_body": False}],
        [(b"content-length", b"11")],
    )
    assert not called
    assert sent[0]["status"] == 413


def test_request_body_limit_rejects_chunked_accumulation_before_endpoint():
    called, sent = _run_body_limit(
        [
            {"type": "http.request", "body": b"123456", "more_body": True},
            {"type": "http.request", "body": b"78901", "more_body": False},
        ],
        [],
    )
    assert not called
    assert sent[0]["status"] == 413


def test_oversized_total_multipart_body_is_rejected_before_job_reservation(app_factory):
    app, client, fake = app_factory(max_upload_bytes=20, request_overhead_bytes=10)
    response = upload(client, b"x")
    assert response.status_code == 413
    assert fake.calls == 0
    assert app.state.store._lifecycles == {}


def test_tombstone_retains_generation_quota_and_slot_until_owner_finalizes(app_factory):
    app, _, _ = app_factory(max_jobs=1)
    store = app.state.store
    job_id = "7" * 32
    _, _, _, generation = store.reserve(job_id, 0)
    store.reserve_resources(job_id, generation, 100, 64, 64)
    disk_before = store.stats()[1]
    memory_before = store._reserved_memory_bytes

    assert store.delete(job_id)
    assert store.lifecycle(job_id).state == "tombstoned"
    assert store.stats()[1] == disk_before
    assert store._reserved_memory_bytes == memory_before
    with pytest.raises(StoreCapacityError, match="job limit"):
        store.reserve("8" * 32, 0)

    assert store.finalize_creation(job_id, generation, "cancelled")
    assert store.stats() == (0, 0)
    assert store._reserved_memory_bytes == 0


def test_successful_request_releases_all_transient_memory_charges(app_factory):
    app, client, _ = app_factory()
    response = upload(client, image_bytes(size=(32, 32)))
    assert response.status_code == 201
    store = app.state.store
    assert store._body_bytes == 0
    assert store._reserved_memory_bytes == 0
    assert store._generation_leases == {}
    assert store._body_leases == {}


def test_body_reservation_remains_while_upload_copy_is_charged(app_factory):
    app, _, _ = app_factory(inflight_body_quota_bytes=1000, memory_quota_bytes=2000)
    store = app.state.store
    body = store.reserve_body(500)
    job_id, _, _, generation = store.reserve("9" * 32, 0)

    store.reserve_upload_copy(job_id, generation, 300)
    assert store._body_bytes == 500
    assert store._reserved_memory_bytes == 300
    store.release_body(body.id)
    assert store._body_bytes == 0
    assert store._reserved_memory_bytes == 300
    store.finalize_creation(job_id, generation, "done")
    assert store._reserved_memory_bytes == 0


def test_concurrent_upload_copy_reservations_jointly_include_bodies(app_factory):
    app, _, _ = app_factory(max_jobs=2, inflight_body_quota_bytes=200, memory_quota_bytes=220)
    store = app.state.store
    bodies = [store.reserve_body(80), store.reserve_body(80)]
    generations = [store.reserve("a" * 32, 0)[3], store.reserve("b" * 32, 0)[3]]
    barrier = threading.Barrier(2)

    def reserve_copy(index):
        barrier.wait()
        job_id = ("a" if index == 0 else "b") * 32
        try:
            store.reserve_upload_copy(job_id, generations[index], 50)
            return True
        except StoreCapacityError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        admitted = [future.result() for future in (pool.submit(reserve_copy, 0), pool.submit(reserve_copy, 1))]
    assert sum(admitted) == 1
    assert store._body_bytes + store._reserved_memory_bytes == 210
    for body in bodies:
        store.release_body(body.id)
    for index, generation in enumerate(generations):
        store.finalize_creation(("a" if index == 0 else "b") * 32, generation, "done")


def test_concurrent_decode_working_set_reservations_are_atomic(app_factory):
    app, _, _ = app_factory(max_jobs=2, memory_quota_bytes=500, disk_quota_bytes=100_000)
    store = app.state.store
    generations = [store.reserve("c" * 32, 0)[3], store.reserve("d" * 32, 0)[3]]
    for index, generation in enumerate(generations):
        store.reserve_upload_copy(("c" if index == 0 else "d") * 32, generation, 20)
    barrier = threading.Barrier(2)

    def reserve_decode(index):
        barrier.wait()
        job_id = ("c" if index == 0 else "d") * 32
        try:
            store.reserve_resources(job_id, generations[index], 20, 5, 5)
            return True
        except StoreCapacityError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        admitted = [future.result() for future in (pool.submit(reserve_decode, 0), pool.submit(reserve_decode, 1))]
    assert sum(admitted) == 1
    assert store._reserved_memory_bytes == 340
    for index, generation in enumerate(generations):
        store.finalize_creation(("c" if index == 0 else "d") * 32, generation, "done")


def test_concurrent_body_reservations_are_atomic(app_factory):
    app, _, _ = app_factory(inflight_body_quota_bytes=100, memory_quota_bytes=100)
    store = app.state.store
    barrier = threading.Barrier(2)

    def reserve():
        barrier.wait()
        try:
            return store.reserve_body(80)
        except StoreCapacityError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        leases = [future.result() for future in (pool.submit(reserve), pool.submit(reserve))]

    admitted = [lease for lease in leases if lease is not None]
    assert len(admitted) == 1
    assert store._body_bytes == 80
    store.release_body(admitted[0].id)
    assert store._body_bytes == 0


def test_body_lease_is_held_through_endpoint_and_released(app_factory):
    app, _, _ = app_factory(inflight_body_quota_bytes=100, memory_quota_bytes=100)
    store = app.state.store
    observed = []

    async def endpoint(scope, receive, send):
        observed.append(store._body_bytes)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = RequestBodyLimitMiddleware(endpoint, 10, store)

    async def run():
        messages = [{"type": "http.request", "body": b"12345", "more_body": False}]

        async def receive():
            return messages.pop(0)

        async def send(message):
            pass

        await middleware(
            {"type": "http", "method": "POST", "path": "/other", "headers": []},
            receive,
            send,
        )

    asyncio.run(run())
    assert observed == [10]
    assert store._body_bytes == 0
    assert store._reserved_disk_bytes == 0


def test_anonymous_create_at_job_limit_stops_before_multipart_endpoint(app_factory):
    app, _, _ = app_factory(max_jobs=1)
    store = app.state.store
    _, _, _, generation = store.reserve("a" * 32, 0)
    called, sent = False, []

    async def endpoint(scope, receive, send):
        nonlocal called
        called = True

    middleware = RequestBodyLimitMiddleware(endpoint, 100, store)

    async def run():
        messages = [{"type": "http.request", "body": b'multipart without an id', "more_body": False}]

        async def receive():
            return messages.pop(0)

        async def send(message):
            sent.append(message)

        await middleware(
            {"type": "http", "method": "POST", "path": "/api/jobs", "headers": []},
            receive,
            send,
        )

    asyncio.run(run())
    assert called
    assert sent == []
    store.finalize_creation("a" * 32, generation, "done")


def test_shutdown_timeout_keeps_active_generation_tracked(app_factory):
    app, _, _ = app_factory(shutdown_wait_seconds=0)
    store = app.state.store
    job_id, _, _, generation = store.reserve("b" * 32, 0)
    store.reserve_resources(job_id, generation, 100, 16, 16)
    accounted = store.stats()[1]

    with pytest.raises(StoreDeletionError, match=f"generation:{generation}"):
        store.shutdown()
    assert generation in store._generation_leases
    assert store.stats()[1] == accounted

    store.finalize_creation(job_id, generation, "shutdown")
    store.shutdown()
    assert store.stats() == (0, 0)


def test_stale_creating_recovery_never_reclaims_an_active_owner(app_factory):
    app, _, _ = app_factory(job_ttl_seconds=1)
    store = app.state.store
    job_id, _, lifecycle, generation = store.reserve("f" * 32, 0)
    store._lifecycles[job_id].updated_at = time.monotonic() - 2

    assert store.cleanup_expired() == 0
    assert lifecycle.state == "creating"

    with store._lock:
        store._generation_leases.pop(generation)
    assert store.cleanup_expired() == 1
    assert store.lifecycle(job_id).state == "failed"


def test_incomplete_directory_scan_uses_conservative_quarantine_charge(app_factory, monkeypatch):
    app, _, _ = app_factory()
    store = app.state.store
    directory = store.root / "job-incomplete"
    directory.mkdir()
    import app.store as store_module

    def incomplete_walk(path, onerror=None):
        assert onerror is not None
        onerror(OSError("unreadable"))
        return iter(())

    monkeypatch.setattr(store_module.os, "walk", incomplete_walk)
    quarantine = store._quarantine("c" * 32, "generation", directory, OSError("busy"), 4096)
    assert quarantine.disk_bytes == 4096
    assert store.stats() == (0, 4096)
    assert store._cleanup_quarantine(quarantine.id)
    assert store.stats() == (0, 0)


def test_incompressible_png_output_stays_within_metered_reservation(app_factory):
    app, _, _ = app_factory(disk_quota_bytes=2 * 1024 * 1024)
    store = app.state.store
    job_id, _, _, generation = store.reserve("d" * 32, 0)
    original = Image.frombytes("RGB", (256, 256), os.urandom(256 * 256 * 3))
    mask = Image.frombytes("L", (256, 256), os.urandom(256 * 256))
    reserved, _ = store.reserve_resources(job_id, generation, 100, 256, 256)

    job = store.create(original, mask, job_id, generation)
    assert job.disk_bytes <= reserved
    store.finalize_creation(job_id, generation)
    store.delete(job_id)


@pytest.mark.parametrize("failure_stage", ["inference", "encode"])
def test_generation_failure_drops_buffers_before_single_finalization(
    app_factory, monkeypatch, failure_stage,
):
    import app.main as main_module

    app, _, _ = app_factory()
    store = app.state.store
    job_id, _, _, generation = store.reserve(("61" if failure_stage == "inference" else "62") * 16, 0)
    references = []
    real_decode = main_module.decode_upload
    real_finalize = store.finalize_creation
    finalize_calls = []

    def tracked_decode(data, max_pixels):
        image = real_decode(data, max_pixels)
        references.append(weakref.ref(image))
        return image

    class FailingInference:
        @staticmethod
        def remove(image):
            if failure_stage == "inference":
                raise RuntimeError("inference failed")
            mask = Image.new("L", image.size, 255)
            references.append(weakref.ref(mask))
            return mask

    def fail_encode(image, path, max_bytes=None):
        raise OSError("encode failed")

    def observed_finalize(*args):
        finalize_calls.append(args)
        assert store._reserved_memory_bytes > 0
        assert all(reference() is None for reference in references)
        return real_finalize(*args)

    monkeypatch.setattr(main_module, "decode_upload", tracked_decode)
    monkeypatch.setattr(store, "finalize_creation", observed_finalize)
    if failure_stage == "encode":
        monkeypatch.setattr(store, "_save_private", fail_encode)

    with pytest.raises(main_module.GenerationFailure) as caught:
        main_module._generate_job(
            store,
            FailingInference(),
            app.state.settings,
            image_bytes(size=(32, 32)),
            job_id,
            generation,
        )

    assert caught.value.classification == "generation"
    assert len(finalize_calls) == 1
    assert generation not in store._generation_leases
    assert store._reserved_memory_bytes == 0



def test_generation_baseexception_finalizer_releases_resources(app_factory):
    from app.main import GenerationFailure, _generate_job

    class Fatal(BaseException):
        pass

    class FatalInference:
        @staticmethod
        def remove(image):
            raise Fatal("cancelled")

    app, _, _ = app_factory()
    store = app.state.store
    job_id, _, _, generation = store.reserve("e" * 32, 0)

    with pytest.raises(GenerationFailure) as caught:
        _generate_job(store, FatalInference(), app.state.settings, image_bytes(size=(32, 32)), job_id, generation)
    assert caught.value.classification == "generation"
    assert generation not in store._generation_leases
    assert store._reserved_memory_bytes == 0
    assert store.stats() == (0, 0)


def test_delete_during_inference_keeps_generation_quota_until_owner_exits(app_factory):
    from app.main import GenerationFailure, _generate_job

    entered = threading.Event()
    release = threading.Event()

    class BlockingInference:
        @staticmethod
        def remove(image):
            entered.set()
            assert release.wait(2)
            return Image.new("L", image.size, 255)

    app, _, _ = app_factory(max_jobs=1)
    store = app.state.store
    job_id, _, _, generation = store.reserve("f" * 32, 0)

    with ThreadPoolExecutor(max_workers=1) as pool:
        owner = pool.submit(
            _generate_job,
            store,
            BlockingInference(),
            app.state.settings,
            image_bytes(size=(32, 32)),
            job_id,
            generation,
        )
        assert entered.wait(1)
        accounted_disk = store.stats()[1]
        accounted_memory = store._reserved_memory_bytes

        assert store.delete(job_id)
        assert store.lifecycle(job_id).state == "tombstoned"
        assert store.stats()[1] == accounted_disk
        assert store._reserved_memory_bytes == accounted_memory
        with pytest.raises(StoreCapacityError, match="job limit"):
            store.reserve("0" * 32, 0)

        release.set()
        with pytest.raises(GenerationFailure) as caught:
            owner.result(timeout=2)
        assert caught.value.classification == "terminal"

    assert generation not in store._generation_leases
    assert store.stats() == (0, 0)
    assert store._reserved_memory_bytes == 0


def test_cancelled_error_finalizes_generation_owner(app_factory):
    from app.main import _generate_job

    class CancelledInference:
        @staticmethod
        def remove(image):
            raise asyncio.CancelledError()

    app, _, _ = app_factory()
    store = app.state.store
    job_id, _, _, generation = store.reserve("1" * 32, 0)

    with pytest.raises(asyncio.CancelledError):
        _generate_job(
            store,
            CancelledInference(),
            app.state.settings,
            image_bytes(size=(32, 32)),
            job_id,
            generation,
        )

    assert generation not in store._generation_leases
    assert store.lifecycle(job_id).state == "failed"
    assert store._reserved_memory_bytes == 0
    assert store.stats() == (0, 0)


def test_shutdown_waits_for_active_generation_owner(app_factory):
    from app.main import GenerationFailure, _generate_job

    entered = threading.Event()
    release = threading.Event()

    class BlockingInference:
        @staticmethod
        def remove(image):
            entered.set()
            assert release.wait(2)
            return Image.new("L", image.size, 255)

    app, _, _ = app_factory(shutdown_wait_seconds=2)
    store = app.state.store
    job_id, _, _, generation = store.reserve("2" * 32, 0)

    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(
            _generate_job,
            store,
            BlockingInference(),
            app.state.settings,
            image_bytes(size=(32, 32)),
            job_id,
            generation,
        )
        assert entered.wait(1)
        stopping = pool.submit(store.shutdown)
        time.sleep(0.05)
        assert not stopping.done()
        assert generation in store._generation_leases
        assert store.stats()[1] > 0

        release.set()
        with pytest.raises(GenerationFailure) as caught:
            owner.result(timeout=2)
        assert caught.value.classification == "terminal"
        stopping.result(timeout=2)

    assert generation not in store._generation_leases
    assert store.lifecycle(job_id).state == "failed"
    assert store.stats() == (0, 0)


def test_shutdown_preserves_published_job_until_worker_memory_release(app_factory, monkeypatch):
    from app.main import _generate_job

    published = threading.Event()
    release = threading.Event()

    class ImmediateInference:
        @staticmethod
        def remove(image):
            return Image.new("L", image.size, 255)

    app, _, _ = app_factory(shutdown_wait_seconds=2)
    store = app.state.store
    job_id, _, _, generation = store.reserve("21" * 16, 0)
    real_release = store.release_worker_memory

    def blocked_release(owner_job_id, owner_generation):
        published.set()
        assert release.wait(2)
        return real_release(owner_job_id, owner_generation)

    monkeypatch.setattr(store, "release_worker_memory", blocked_release)
    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(
            _generate_job,
            store,
            ImmediateInference(),
            app.state.settings,
            image_bytes(size=(32, 32)),
            job_id,
            generation,
        )
        assert published.wait(1)
        job = store._jobs[job_id]
        stopping = pool.submit(store.shutdown)
        deadline = time.monotonic() + 1
        while not store._closing and time.monotonic() < deadline:
            time.sleep(0.001)

        assert store._closing
        assert not stopping.done()
        assert store.lifecycle(job_id).state == "live"
        assert job.directory.exists()

        release.set()
        owner.result(timeout=2)
        stopping.result(timeout=2)

    assert generation not in store._generation_leases
    assert job_id not in store._jobs
    assert not job.directory.exists()
    assert store.stats() == (0, 0)


def test_publish_atomically_retires_owner_and_memory(app_factory):
    app, _, _ = app_factory()
    store = app.state.store
    job_id, _, _, generation = store.reserve("3" * 32, 0)
    store.reserve_resources(job_id, generation, 100, 8, 6)

    job = store.create(
        Image.new("RGB", (8, 6), "red"),
        Image.new("L", (8, 6), 255),
        job_id,
        generation,
    )

    assert generation in store._generation_leases
    assert store._reserved_memory_bytes > 0
    assert store.lifecycle(job_id).state == "live"
    assert store.release_worker_memory(job_id, generation)
    assert generation not in store._generation_leases
    assert store._reserved_memory_bytes == 0
    assert store.delete(job_id)
    assert job_id not in store._jobs
    assert not job.directory.exists()
    assert store.finalize_creation(job_id, generation) is False
    assert store.lifecycle(job_id).state == "tombstoned"


def test_failed_cleanup_keeps_generation_charge_during_scan(app_factory, monkeypatch):
    app, _, _ = app_factory(max_jobs=2, disk_quota_bytes=3000)
    store = app.state.store
    first_id, _, _, first_generation = store.reserve("4" * 32, 0)
    reserved, _ = store.reserve_resources(first_id, first_generation, 100, 8, 6)
    directory = store.root / f"job-{first_id}-{first_generation}"
    directory.mkdir(mode=0o700)
    (directory / "partial").write_bytes(b"partial")
    with store._lock:
        store._generation_leases[first_generation].directory = directory
    second_id, _, _, second_generation = store.reserve("5" * 32, 0)

    import app.store as store_module
    scan_entered = threading.Event()
    release_scan = threading.Event()
    real_scan = store._directory_bytes
    real_rmtree = store_module.shutil.rmtree
    monkeypatch.setattr(store_module.shutil, "rmtree", lambda path: (_ for _ in ()).throw(OSError("busy")))

    def blocked_scan(path):
        scan_entered.set()
        assert release_scan.wait(2)
        return real_scan(path)

    monkeypatch.setattr(store, "_directory_bytes", blocked_scan)
    with ThreadPoolExecutor(max_workers=1) as pool:
        finalizing = pool.submit(store.finalize_creation, first_id, first_generation, "failed")
        assert scan_entered.wait(1)
        assert store.stats()[1] == reserved
        with pytest.raises(StoreCapacityError, match="disk quota"):
            store.reserve_resources(second_id, second_generation, 100, 8, 6)
        release_scan.set()
        with pytest.raises(StoreDeletionError):
            finalizing.result(timeout=2)

    assert first_generation not in store._generation_leases
    assert store.stats()[1] > 0
    store.finalize_creation(second_id, second_generation, "done")
    monkeypatch.setattr(store_module.shutil, "rmtree", real_rmtree)
    store.cleanup_expired()


def test_partial_create_cleanup_atomically_replaces_reservation_with_conservative_quarantine(
    app_factory, monkeypatch,
):
    from app.store import StoreCreationError
    import app.store as store_module

    app, _, _ = app_factory()
    store = app.state.store
    job_id, _, _, generation = store.reserve("6" * 32, 0)
    reserved, _ = store.reserve_resources(job_id, generation, 100, 8, 6)
    real_rmtree = store_module.shutil.rmtree

    monkeypatch.setattr(
        store, "_save_private", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("encode failed"))
    )
    monkeypatch.setattr(
        store_module.shutil, "rmtree", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("busy"))
    )
    monkeypatch.setattr(store, "_directory_bytes", lambda directory: (0, False))

    with pytest.raises(StoreCreationError) as caught:
        store.create(
            Image.new("RGB", (8, 6)), Image.new("L", (8, 6)), job_id, generation
        )

    assert caught.value.classification == "cleanup"
    quarantine = next(iter(store._quarantines.values()))
    assert quarantine.disk_bytes >= reserved
    assert generation not in store._generation_leases
    assert store._reserved_disk_bytes == 0
    assert store.stats() == (0, quarantine.disk_bytes)

    monkeypatch.setattr(store_module.shutil, "rmtree", real_rmtree)
    assert store._cleanup_quarantine(quarantine.id)
    assert store.stats() == (0, 0)


def test_shutdown_closes_admission_before_waiting_for_finalizer(app_factory):
    app, _, _ = app_factory(shutdown_wait_seconds=2)
    store = app.state.store
    job_id, _, _, generation = store.reserve("7" * 32, 0)

    with ThreadPoolExecutor(max_workers=1) as pool:
        stopping = pool.submit(store.shutdown)
        deadline = time.monotonic() + 1
        while not store._closing and time.monotonic() < deadline:
            time.sleep(0.001)
        assert store._closing
        with pytest.raises(StoreCapacityError, match="shutting down"):
            store.reserve("8" * 32, 0)
        with pytest.raises(StoreCapacityError, match="shutting down"):
            store.reserve_body(1)
        store.finalize_creation(job_id, generation, "shutdown")
        stopping.result(timeout=2)


def test_shutdown_ignores_cleanup_failure_resolved_by_quarantine_retry(app_factory, monkeypatch):
    app, client, _ = app_factory()
    store = app.state.store
    job_id = upload(client, image_bytes()).json()["id"]
    job = store._jobs[job_id]
    import app.store as store_module
    real_rmtree = store_module.shutil.rmtree
    attempts = 0

    def once(path, *args, **kwargs):
        nonlocal attempts
        if path == job.directory and attempts == 0:
            attempts += 1
            raise OSError("busy once")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(store_module.shutil, "rmtree", once)
    store.shutdown()
    assert store.stats() == (0, 0)
    assert not store._quarantines


def test_terminal_id_post_stays_gone_without_aba_mutation(app_factory):
    app, client, fake = app_factory(job_ttl_seconds=1)
    job_id = upload(client, image_bytes()).json()["id"]
    assert client.delete(f"/api/jobs/{job_id}").status_code == 204
    lifecycle = app.state.store.lifecycle(job_id)
    app.state.store._lifecycles[job_id].updated_at = time.monotonic() - 10
    app.state.store.cleanup_expired()
    calls = fake.calls

    response = client.post(
        "/api/jobs",
        data={"job_id": job_id},
        files={"file": ("photo.png", image_bytes(color=(1, 2, 3)), "image/png")},
    )
    assert response.status_code == 410
    assert fake.calls == calls
    assert client.delete(f"/api/jobs/{job_id}").status_code == 410
    assert job_id not in app.state.store._jobs


def test_read_limited_uses_one_bounded_read_and_closes():
    class Upload:
        def __init__(self, data):
            self.data = data
            self.reads = []
            self.closed = False

        async def read(self, size):
            self.reads.append(size)
            return self.data[:size]

        async def close(self):
            self.closed = True

    upload_file = Upload(b"12345")
    assert asyncio.run(_read_limited(upload_file, 5)) == b"12345"
    assert upload_file.reads == [6]
    assert upload_file.closed


def test_unknown_deletes_do_not_consume_ids_or_grow_terminal_metadata(app_factory):
    app, client, _ = app_factory(job_ttl_seconds=1)
    store = app.state.store
    before_ids = set(store._used_job_ids)

    for value in range(500):
        job_id = f"{value:032x}"
        assert client.delete(f"/api/jobs/{job_id}").status_code == 404

    assert store._lifecycles == {}
    assert store._used_job_ids == before_ids


def test_terminal_details_expire_but_used_id_remains_terminal(app_factory):
    app, _, _ = app_factory(job_ttl_seconds=1, terminal_registry_max=600)
    store = app.state.store
    old_id = "a1" * 16

    for value in range(500):
        job_id = f"{value + 1000:032x}"
        _, owner, lifecycle, generation = store.reserve(job_id, 0)
        assert owner
        store.finalize_creation(job_id, generation, f"private error {value}")
        store._lifecycles[job_id].updated_at = time.monotonic() - 2

    _, _, old_lifecycle, old_generation = store.reserve(old_id, 0)
    store.finalize_creation(old_id, old_generation, "secret detail")
    store._lifecycles[old_id].updated_at = time.monotonic() - 2
    store.cleanup_expired()

    assert store._lifecycles == {}
    assert len(store._used_job_ids) == 501
    with pytest.raises(JobTerminal):
        with store.locked(old_id):
            pass
    assert store.reserve(old_id, 0)[1] is False


def test_lookup_is_lifecycle_aware_and_accepts_hyphenated_ids(app_factory):
    app, client, _ = app_factory()
    store = app.state.store
    job_id = "12345678123456781234567812345678"
    hyphenated = "12345678-1234-5678-1234-567812345678"
    _, _, _, generation = store.reserve(job_id, 0)

    for suffix in ("original", "preview", "export"):
        assert client.get(f"/api/jobs/{hyphenated}/{suffix}").status_code == 202
    assert append_stroke(client, hyphenated, "remove").status_code == 202
    assert client.delete(f"/api/jobs/{hyphenated}/strokes/last").status_code == 202
    assert client.delete(f"/api/jobs/{hyphenated}/strokes").status_code == 202

    store.finalize_creation(job_id, generation, "failed privately")
    for suffix in ("original", "preview", "export"):
        assert client.get(f"/api/jobs/{hyphenated}/{suffix}").status_code == 410


def test_lifecycle_snapshots_are_frozen_and_coherent_across_delete(app_factory):
    app, client, _ = app_factory()
    job_id = upload(client, image_bytes(size=(9, 7))).json()["id"]
    snapshot = app.state.store.lifecycle(job_id)

    assert snapshot.state == "live"
    assert snapshot.job.width == 9
    assert snapshot.job.height == 7
    with pytest.raises(AttributeError):
        snapshot.state = "failed"
    with pytest.raises(AttributeError):
        snapshot.job.width = 1

    assert client.delete(f"/api/jobs/{job_id}").status_code == 204
    assert snapshot.state == "live"
    assert snapshot.job.width == 9
    assert app.state.store.lifecycle(job_id).state == "tombstoned"


def test_exact_terminal_registry_has_no_false_positives_and_rejects_when_full(app_factory):
    app, _, _ = app_factory(max_jobs=4, terminal_registry_max=2)
    store = app.state.store
    first = "01" * 16
    second = "02" * 16
    unseen = "03" * 16

    for job_id in (first, second):
        _, owner, _, generation = store.reserve(job_id, 0)
        assert owner
        assert store.finalize_creation(job_id, generation, "done")

    assert unseen not in store._used_job_ids
    assert store.lifecycle(unseen) is None
    assert store.reserve(first, 0)[1] is False
    with pytest.raises(StoreCapacityError, match="registry is full"):
        store.reserve(unseen, 0)
    assert len(store._used_job_ids) == 2


def test_published_job_keeps_worker_memory_until_finalizer(app_factory):
    app, _, _ = app_factory(max_jobs=2, memory_quota_bytes=1000)
    store = app.state.store
    first, _, _, first_generation = store.reserve("11" * 16, 0)
    store.reserve_resources(first, first_generation, 100, 8, 6)
    store.create(Image.new("RGB", (8, 6)), Image.new("L", (8, 6)), first, first_generation)

    held = store._reserved_memory_bytes
    assert held > 0
    second, _, _, second_generation = store.reserve("12" * 16, 0)
    with pytest.raises(StoreCapacityError, match="memory limit"):
        store.reserve_resources(second, second_generation, 100, 8, 6)

    assert store.release_worker_memory(first, first_generation)
    store.reserve_resources(second, second_generation, 100, 8, 6)
    store.finalize_creation(second, second_generation, "done")
    store.delete(first)


def test_successful_shutdown_store_can_start_and_accept_work_again(tmp_path):
    settings = Settings(temp_root=tmp_path / "restart", process_lock=False)
    store = JobStore(settings)
    store.startup()
    store.shutdown()
    assert store._closing

    store.startup()
    assert not store._closing
    job_id, owner, _, generation = store.reserve("21" * 16, 0)
    assert owner
    store.finalize_creation(job_id, generation, "done")
    store.shutdown()


def test_lifespan_runs_shutdown_when_reaper_and_shutdown_both_fail(tmp_path, monkeypatch):
    app = create_app(
        Settings(
            temp_root=tmp_path / "lifespan",
            process_lock=False,
            enforce_loopback=False,
            cleanup_interval_seconds=0,
        ),
        FakeRemover(),
    )
    store = app.state.store
    reaped = threading.Event()
    shutdown_called = threading.Event()

    def fail_reaper():
        reaped.set()
        raise RuntimeError("reaper failed")

    def fail_shutdown():
        shutdown_called.set()
        raise StoreDeletionError("shutdown failed")

    monkeypatch.setattr(store, "cleanup_expired", fail_reaper)
    monkeypatch.setattr(store, "shutdown", fail_shutdown)

    async def run():
        async with app.router.lifespan_context(app):
            while not reaped.is_set():
                await asyncio.sleep(0)
            await asyncio.sleep(0.01)

    with pytest.raises(StoreDeletionError, match="shutdown failed") as caught:
        asyncio.run(run())
    assert shutdown_called.is_set()
    assert isinstance(caught.value.__context__, RuntimeError)
    assert str(caught.value.__context__) == "reaper failed"


def test_create_timestamps_are_captured_at_final_publication(app_factory, monkeypatch):
    app, _, _ = app_factory(job_ttl_seconds=0.05)
    store = app.state.store
    job_id, _, _, generation = store.reserve("31" * 16, 0)
    store.reserve_resources(job_id, generation, 100, 8, 6)
    real_save = store._save_private
    saves = 0

    def slow_save(image, path, max_bytes=None):
        nonlocal saves
        saves += 1
        if saves == 2:
            time.sleep(0.08)
        return real_save(image, path, max_bytes)

    monkeypatch.setattr(store, "_save_private", slow_save)
    before_publish = time.monotonic()
    job = store.create(
        Image.new("RGB", (8, 6)),
        Image.new("L", (8, 6)),
        job_id,
        generation,
    )
    assert job.created_at >= before_publish + 0.05
    assert store.cleanup_expired() == 0
    store.release_worker_memory(job_id, generation)
    store.delete(job_id)


def test_cancelled_create_waits_for_blocked_reservation_and_retires_owner(app_factory, monkeypatch):
    from fastapi import UploadFile
    from starlette.requests import Request

    app, _, _ = app_factory()
    store = app.state.store
    entered = threading.Event()
    release = threading.Event()
    real_reserve = store.reserve
    job_id = "41" * 16

    def blocked_reserve(value):
        entered.set()
        assert release.wait(2)
        return real_reserve(value, 0)

    monkeypatch.setattr(store, "reserve", blocked_reserve)
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/api/jobs" and "POST" in route.methods)

    async def run():
        request = Request({"type": "http", "method": "POST", "path": "/api/jobs", "headers": [], "state": {}})
        upload_file = UploadFile(io.BytesIO(image_bytes()), filename="photo.png")
        task = asyncio.create_task(endpoint(request=request, file=upload_file, job_id=job_id))
        while not entered.is_set():
            await asyncio.sleep(0)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert store.lifecycle(job_id).state == "tombstoned"
    assert not store._generation_leases
    assert store.stats() == (0, 0)


def test_delete_published_job_with_active_worker_lease_removes_live_storage(app_factory):
    app, _, _ = app_factory()
    store = app.state.store
    job_id, _, _, generation = store.reserve("42" * 16, 0)
    store.reserve_resources(job_id, generation, 100, 8, 6)
    job = store.create(Image.new("RGB", (8, 6)), Image.new("L", (8, 6)), job_id, generation)

    assert store.delete(job_id)
    assert not job.directory.exists()
    assert job_id not in store._jobs
    lifecycle = store.lifecycle(job_id)
    assert lifecycle.state == "tombstoned" and lifecycle.job is None
    assert store._generation_leases[generation].cancelled
    assert store.release_worker_memory(job_id, generation)
    assert store.stats() == (0, 0)


def test_parser_spool_reservations_are_joint_and_atomic(app_factory):
    app, _, _ = app_factory(memory_quota_bytes=150, inflight_body_quota_bytes=200, disk_quota_bytes=1000)
    store = app.state.store
    leases = [store.reserve_body(50), store.reserve_body(50)]
    barrier = threading.Barrier(2)

    def reserve_spool(lease):
        barrier.wait()
        try:
            # Charge the aggregate full body even if every individual parser
            # part could remain below the spool threshold.
            store.reserve_parser_spool(lease.id, 50, 1)
            return True
        except StoreCapacityError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        admitted = [future.result() for future in (pool.submit(reserve_spool, leases[0]), pool.submit(reserve_spool, leases[1]))]
    assert sum(admitted) == 1
    assert store._body_bytes == 150
    assert store._reserved_disk_bytes == 50
    for lease in leases:
        store.release_body(lease.id)
    assert store._body_bytes == 0
    assert store._reserved_disk_bytes == 0


def test_loopback_middleware_holds_render_lease_through_slow_outer_send(app_factory):
    from app.main import LoopbackOnlyMiddleware, RenderLeaseResponse

    app, _, _ = app_factory()
    store = app.state.store
    job_id, _, _, generation = store.reserve("50" * 16, 0)
    store.reserve_resources(job_id, generation, 10, 8, 6)
    store.create(Image.new("RGB", (8, 6)), Image.new("L", (8, 6)), job_id, generation)
    store.release_worker_memory(job_id, generation)
    lease = store.reserve_render(job_id, "original")
    response = RenderLeaseResponse(b"data", store=store, lease_id=lease.id)
    middleware = LoopbackOnlyMiddleware(response)
    body_entered = asyncio.Event()
    release_send = asyncio.Event()
    sent = []

    async def run():
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def slow_send(message):
            sent.append(message)
            if message["type"] == "http.response.body":
                body_entered.set()
                await release_send.wait()

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/jobs/example/original",
            "headers": [(b"host", b"127.0.0.1:8000")],
            "client": ("127.0.0.1", 54321),
        }
        transmission = asyncio.create_task(middleware(scope, receive, slow_send))
        await body_entered.wait()
        assert lease.id in store._render_leases
        assert store._reserved_memory_bytes == lease.reserved_memory_bytes
        release_send.set()
        await transmission

    asyncio.run(run())
    assert lease.id not in store._render_leases
    assert store._reserved_memory_bytes == 0
    start = next(message for message in sent if message["type"] == "http.response.start")
    headers = dict(start["headers"])
    assert headers[b"cache-control"] == b"no-store"
    assert headers[b"x-content-type-options"] == b"nosniff"
    assert headers[b"referrer-policy"] == b"no-referrer"
    store.delete(job_id)



def test_render_leases_exclude_concurrent_work_and_release(app_factory):
    app, _, _ = app_factory(memory_quota_bytes=1800)
    store = app.state.store
    job_id, _, _, generation = store.reserve("51" * 16, 0)
    store.reserve_resources(job_id, generation, 10, 8, 6)
    store.create(Image.new("RGB", (8, 6)), Image.new("L", (8, 6)), job_id, generation)
    store.release_worker_memory(job_id, generation)

    first = store.reserve_render(job_id, "export")
    with pytest.raises(StoreCapacityError, match="render memory"):
        store.reserve_render(job_id, "export")
    store.release_render(first.id)
    second = store.reserve_render(job_id, "export")
    store.release_render(second.id)
    assert store._reserved_memory_bytes == 0
    store.delete(job_id)


def test_render_response_releases_lease_after_send_failure(app_factory):
    from app.main import RenderLeaseResponse

    app, _, _ = app_factory()
    store = app.state.store
    job_id, _, _, generation = store.reserve("52" * 16, 0)
    store.reserve_resources(job_id, generation, 10, 8, 6)
    store.create(Image.new("RGB", (8, 6)), Image.new("L", (8, 6)), job_id, generation)
    store.release_worker_memory(job_id, generation)
    lease = store.reserve_render(job_id, "original")
    response = RenderLeaseResponse(b"data", store=store, lease_id=lease.id)

    async def run():
        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            raise ConnectionError("disconnected")

        with pytest.raises(ConnectionError):
            await response({"type": "http"}, receive, send)

    asyncio.run(run())
    assert lease.id not in store._render_leases
    assert store._reserved_memory_bytes == 0
    store.delete(job_id)


def test_cancel_generation_does_not_cross_publication_commit_point(app_factory):
    app, _, _ = app_factory()
    store = app.state.store
    job_id, _, _, generation = store.reserve("53" * 16, 0)
    store.reserve_resources(job_id, generation, 10, 8, 6)
    job = store.create(Image.new("RGB", (8, 6)), Image.new("L", (8, 6)), job_id, generation)

    assert store.cancel_generation(job_id, generation) is False
    assert store.lifecycle(job_id).state == "live"
    assert store._jobs[job_id] is job
    assert store.release_worker_memory(job_id, generation)
    store.delete(job_id)


def test_live_partial_delete_transfers_storage_away_from_worker(app_factory, monkeypatch):
    app, _, _ = app_factory()
    store = app.state.store
    job_id, _, _, generation = store.reserve("54" * 16, 0)
    store.reserve_resources(job_id, generation, 10, 8, 6)
    job = store.create(Image.new("RGB", (8, 6)), Image.new("L", (8, 6)), job_id, generation)
    import app.store as store_module
    real_rmtree = store_module.shutil.rmtree
    calls = 0

    def partial(path, *args, **kwargs):
        nonlocal calls
        if path == job.directory:
            calls += 1
            if calls == 1:
                (job.directory / "mask.png").unlink()
                raise OSError("partial")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(store_module.shutil, "rmtree", partial)
    with pytest.raises(StoreDeletionError):
        store.delete(job_id)
    lease = store._generation_leases[generation]
    assert lease.directory is None and lease.storage_transferred_to_quarantine
    accounted = store.stats()[1]
    assert store.release_worker_memory(job_id, generation)
    assert calls == 1
    assert store.stats()[1] == accounted
    assert len(store._quarantines) == 1
    store.cleanup_expired()
    assert calls == 2
    assert store.stats() == (0, 0)
