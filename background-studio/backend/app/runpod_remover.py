from __future__ import annotations

import base64
import binascii
import io
import json
import math
import subprocess
import time
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx
from PIL import Image, UnidentifiedImageError

from .config import Settings
from .remover import BiRefNetHRRemover, Remover, letterbox

CANVAS_SIZE = 2048
SUPPORTED_CANVAS_SIZES = frozenset({1024, 1536, 2048})
COMPACT_INPUT_THRESHOLD = 1024
MAX_LOSSLESS_INPUT_BYTES = 4 * 1024 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
TILE_OVERLAP_RATIO = 0.125
TILE_TRIGGER_RATIO = 1.25
KEYCHAIN_ENDPOINT_ACCOUNT = "endpoint-url"
KEYCHAIN_API_KEY_ACCOUNT = "api-key"
KEYCHAIN_TOKEN_ACCOUNT = "worker-token"
TRANSIENT_STATUS_CODES = {429, 430, 502, 503}
STARTUP_STATUS_ATTEMPTS = 31
STARTUP_RETRY_DELAY_SECONDS = 10.0


class RunpodConfigurationError(RuntimeError):
    """Runpod is selected but its local configuration is invalid."""


class RunpodInferenceError(RuntimeError):
    """The remote inference request failed without exposing remote internals."""


def _keychain_password(service: str, account: str) -> str | None:
    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                service,
                "-a",
                account,
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RunpodConfigurationError(
            "Unable to read Background Studio's Runpod configuration "
            "from macOS Keychain."
        ) from exc

    if result.returncode == 44:
        return None
    if result.returncode != 0:
        raise RunpodConfigurationError(
            "Unable to read Background Studio's Runpod configuration "
            "from macOS Keychain."
        )
    value = result.stdout.rstrip("\r\n")
    return value or None


def _validated_endpoint_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise RunpodConfigurationError(
            "The Runpod endpoint URL in macOS Keychain must be an HTTPS URL "
            "without credentials, a query, or a fragment."
        )
    return value.rstrip("/")


class RunpodRemover:
    def __init__(
        self,
        endpoint_url: str,
        api_key: str,
        worker_token: str,
        *,
        connect_timeout_seconds: float = 10.0,
        read_timeout_seconds: float = 300.0,
        canvas_size: int = CANVAS_SIZE,
        client_factory: Callable[..., httpx.Client] = httpx.Client,
    ) -> None:
        if canvas_size not in SUPPORTED_CANVAS_SIZES:
            raise RunpodConfigurationError(
                "Runpod canvas size must be 1024, 1536, or 2048."
            )
        if not api_key:
            raise RunpodConfigurationError(
                "The Runpod API key in macOS Keychain is empty."
            )
        if not worker_token:
            raise RunpodConfigurationError(
                "The Runpod worker token in macOS Keychain is empty."
            )
        self._endpoint_url = _validated_endpoint_url(endpoint_url)
        self._api_key = api_key
        self._worker_token = worker_token
        self._canvas_size = canvas_size
        self._client_factory = client_factory
        self._timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            write=30.0,
            pool=connect_timeout_seconds,
        )

    @classmethod
    def from_keychain(
        cls,
        settings: Settings,
        *,
        required: bool,
    ) -> "RunpodRemover | None":
        service = settings.runpod_keychain_service
        endpoint_url = _keychain_password(
            service,
            KEYCHAIN_ENDPOINT_ACCOUNT,
        )
        token = _keychain_password(
            service,
            KEYCHAIN_TOKEN_ACCOUNT,
        )
        api_key = _keychain_password(
            service,
            KEYCHAIN_API_KEY_ACCOUNT,
        )

        if (
            endpoint_url is None
            and token is None
            and api_key is None
            and not required
        ):
            return None
        if (
            endpoint_url is None
            or token is None
            or api_key is None
        ):
            raise RunpodConfigurationError(
                "Runpod configuration is incomplete in macOS Keychain."
            )

        return cls(
            endpoint_url,
            api_key,
            token,
            connect_timeout_seconds=settings.runpod_connect_timeout_seconds,
            read_timeout_seconds=settings.runpod_read_timeout_seconds,
            canvas_size=settings.runpod_canvas_size,
        )

    @staticmethod
    def _encode_canvas(canvas: Image.Image) -> str:
        lossless = io.BytesIO()
        canvas.save(lossless, format="PNG", optimize=False)
        data = lossless.getvalue()
        if (
            max(canvas.size) > COMPACT_INPUT_THRESHOLD
            and len(data) > MAX_LOSSLESS_INPUT_BYTES
        ):
            # A 2048px RGB PNG can exceed Runpod's request limit for textured
            # photos. WebP keeps the larger inference canvas practical while
            # retaining far more detail than the 1024px fallback.
            compact = io.BytesIO()
            canvas.save(
                compact,
                format="WEBP",
                quality=95,
                method=6,
            )
            data = compact.getvalue()
        return base64.b64encode(data).decode("ascii")

    @staticmethod
    def _decode_mask(
        value: object,
        expected_size: int = CANVAS_SIZE,
    ) -> Image.Image:
        if not isinstance(value, str):
            raise RunpodInferenceError(
                "Runpod returned an invalid mask response."
            )
        try:
            data = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise RunpodInferenceError(
                "Runpod returned an invalid mask response."
            ) from exc
        if not data or len(data) > MAX_RESPONSE_BYTES:
            raise RunpodInferenceError(
                "Runpod returned an invalid mask response."
            )

        try:
            with Image.open(io.BytesIO(data)) as source:
                source.load()
                if source.size != (expected_size, expected_size):
                    raise RunpodInferenceError(
                        "Runpod returned a mask with the wrong dimensions."
                    )
                return source.convert("L")
        except (UnidentifiedImageError, OSError) as exc:
            raise RunpodInferenceError(
                "Runpod returned an invalid mask image."
            ) from exc

    @staticmethod
    def _bounded_response_body(response: httpx.Response) -> bytes:
        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > MAX_RESPONSE_BYTES:
                raise RunpodInferenceError(
                    "Runpod returned an oversized response."
                )
        return bytes(body)

    def _request_mask(self, canvas: Image.Image) -> Image.Image:
        payload = {"image_base64": self._encode_canvas(canvas)}
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "X-Background-Studio-Token": self._worker_token,
            "Content-Type": "application/json",
        }

        connect_failures = 0
        for attempt in range(STARTUP_STATUS_ATTEMPTS):
            try:
                with self._client_factory(timeout=self._timeout) as client:
                    with client.stream(
                        "POST",
                        f"{self._endpoint_url}/remove",
                        headers=headers,
                        json=payload,
                    ) as response:
                        body = self._bounded_response_body(response)
                        status_code = response.status_code
            except (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadError,
            ) as exc:
                connect_failures += 1
                if connect_failures < 3:
                    time.sleep(float(connect_failures))
                    continue
                raise RunpodInferenceError(
                    "Runpod could not be reached after multiple attempts."
                ) from exc
            except (
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.PoolTimeout,
            ) as exc:
                raise RunpodInferenceError(
                    "Runpod did not complete the inference request in time. "
                    "The request was not retried."
                ) from exc

            if (
                status_code in TRANSIENT_STATUS_CODES
                and attempt < STARTUP_STATUS_ATTEMPTS - 1
            ):
                time.sleep(STARTUP_RETRY_DELAY_SECONDS)
                continue
            if status_code != 200:
                raise RunpodInferenceError(
                    f"Runpod inference failed with HTTP {status_code}."
                )

            try:
                decoded = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RunpodInferenceError(
                    "Runpod returned an invalid JSON response."
                ) from exc
            if not isinstance(decoded, dict):
                raise RunpodInferenceError(
                    "Runpod returned an invalid JSON response."
                )
            return self._decode_mask(
                decoded.get("mask_base64"),
                self._canvas_size,
            )

        raise RunpodInferenceError(
            "Runpod inference failed after multiple attempts."
        )

    @staticmethod
    def _axis_positions(
        length: int,
        tile_side: int,
        count: int,
    ) -> list[int]:
        if count <= 1 or length <= tile_side:
            return [0]
        span = length - tile_side
        return [
            round(index * span / (count - 1))
            for index in range(count)
        ]

    def _tile_plan(
        self,
        size: tuple[int, int],
    ) -> tuple[int, list[tuple[int, int, int]]]:
        width, height = size
        overlap = max(
            64,
            round(self._canvas_size * TILE_OVERLAP_RATIO),
        )
        trigger = round(self._canvas_size * TILE_TRIGGER_RATIO)

        def axis_count(length: int) -> int:
            if length <= trigger:
                return 1
            return max(
                2,
                math.ceil(length / (self._canvas_size + overlap)),
            )

        columns = axis_count(width)
        rows = axis_count(height)
        tile_side = max(
            math.ceil(width / columns),
            math.ceil(height / rows),
        ) + overlap
        x_positions = self._axis_positions(
            width,
            tile_side,
            columns,
        )
        y_positions = self._axis_positions(
            height,
            tile_side,
            rows,
        )
        return overlap, [
            (x, y, tile_side)
            for y in y_positions
            for x in x_positions
        ]

    @staticmethod
    def _tile_axis_weights(
        length: int,
        start: int,
        end: int,
        overlap: int,
        global_length: int,
    ):
        import numpy as np

        weights = np.ones(length, dtype=np.float32)
        if start > 0:
            weights = np.minimum(
                weights,
                np.clip(
                    (np.arange(length, dtype=np.float32) + 1)
                    / max(1, overlap),
                    0.05,
                    1.0,
                ),
            )
        if end < global_length:
            weights = np.minimum(
                weights,
                np.clip(
                    (np.arange(length - 1, -1, -1, dtype=np.float32) + 1)
                    / max(1, overlap),
                    0.05,
                    1.0,
                ),
            )
        return weights

    def _remove_tiled(self, image: Image.Image) -> Image.Image:
        import numpy as np

        width, height = image.size
        overlap, plan = self._tile_plan(image.size)
        accumulated = np.zeros((height, width), dtype=np.float32)
        weights = np.zeros((height, width), dtype=np.float32)

        for left, top, tile_side in plan:
            right = min(width, left + tile_side)
            bottom = min(height, top + tile_side)
            crop = image.crop((left, top, right, bottom))
            canvas = Image.new(
                "RGB",
                (tile_side, tile_side),
                (0, 0, 0),
            )
            canvas.paste(crop, (0, 0))
            canvas = canvas.resize(
                (self._canvas_size, self._canvas_size),
                Image.Resampling.LANCZOS,
            )
            tile_mask = self._request_mask(canvas).resize(
                (tile_side, tile_side),
                Image.Resampling.LANCZOS,
            )
            tile = np.asarray(
                tile_mask.crop((0, 0, right - left, bottom - top)),
                dtype=np.float32,
            ) / 255.0
            tile_weights = np.outer(
                self._tile_axis_weights(
                    bottom - top,
                    top,
                    bottom,
                    overlap,
                    height,
                ),
                self._tile_axis_weights(
                    right - left,
                    left,
                    right,
                    overlap,
                    width,
                ),
            )
            accumulated[top:bottom, left:right] += tile * tile_weights
            weights[top:bottom, left:right] += tile_weights

        result = np.divide(
            accumulated,
            np.maximum(weights, 1e-6),
        )
        return Image.fromarray(
            np.clip(result * 255.0, 0, 255).astype("uint8"),
            mode="L",
        )

    def remove(self, image: Image.Image) -> Image.Image:
        image = image.convert("RGB")
        if max(image.size) > round(
            self._canvas_size * TILE_TRIGGER_RATIO
        ):
            return self._remove_tiled(image)

        canvas, (left, top, width, height) = letterbox(
            image,
            self._canvas_size,
        )
        square = self._request_mask(canvas)
        cropped = square.crop(
            (left, top, left + width, top + height)
        )
        return cropped.resize(
            image.size,
            Image.Resampling.LANCZOS,
        )


def build_default_remover(settings: Settings) -> Remover:
    backend = settings.remover_backend
    if backend not in {"auto", "local", "runpod"}:
        raise RunpodConfigurationError(
            "BACKGROUND_STUDIO_REMOVER_BACKEND must be auto, local, or runpod."
        )
    if backend == "local":
        return BiRefNetHRRemover()

    remote = RunpodRemover.from_keychain(
        settings,
        required=backend == "runpod",
    )
    return remote or BiRefNetHRRemover()
