from __future__ import annotations

import base64
import binascii
import asyncio
import hmac
import io
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from collections.abc import Callable
from typing import Protocol

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, validator
from starlette.types import ASGIApp, Message, Receive, Scope, Send

LOGGER = logging.getLogger("background_studio.worker")
MODEL_ID = "ZhengPeng7/BiRefNet_HR"
MODEL_REVISION = "707a63fd375513cc01cddd3c4e6125a184157f35"
CANVAS_SIZE = int(
    os.getenv("BACKGROUND_STUDIO_CANVAS_SIZE", "2048")
)
if CANVAS_SIZE not in {1024, 1536, 2048}:
    raise RuntimeError(
        "BACKGROUND_STUDIO_CANVAS_SIZE must be 1024, 1536, or 2048."
    )
MAX_IMAGE_BYTES = 6 * 1024 * 1024
MAX_REQUEST_BYTES = 12 * 1024 * 1024


class InferenceEngine(Protocol):
    def remove(self, image_bytes: bytes) -> bytes:
        raise NotImplementedError


class RemoveRequest(BaseModel):
    image_base64: str

    class Config:
        extra = "forbid"

    @validator("image_base64")
    def validate_encoded_size(cls, value: str) -> str:
        if not value or len(value) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
            raise ValueError("Encoded image is too large.")
        return value


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = dict(scope.get("headers", [])).get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > self.max_bytes:
                    await self._reject(scope, send)
                    return
            except ValueError:
                pass

        messages: list[Message] = []
        total = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                await self._reject(scope, send)
                return
            if not message.get("more_body", False):
                break

        index = 0

        async def replay() -> Message:
            nonlocal index
            if index < len(messages):
                message = messages[index]
                index += 1
                return message
            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }

        await self.app(scope, replay, send)

    @staticmethod
    async def _empty_receive() -> Message:
        return {
            "type": "http.request",
            "body": b"",
            "more_body": False,
        }

    async def _reject(self, scope: Scope, send: Send) -> None:
        response = JSONResponse(
            {"detail": "Request body is too large."},
            status_code=413,
            headers={"Cache-Control": "no-store"},
        )
        await response(scope, self._empty_receive, send)


class BiRefNetCudaEngine:
    def __init__(self) -> None:
        import numpy as np
        import torch
        from transformers import AutoModelForImageSegmentation

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required.")

        self._np = np
        self._torch = torch
        self._device = torch.device("cuda")
        self._model = (
            AutoModelForImageSegmentation
            .from_pretrained(
                MODEL_ID,
                revision=MODEL_REVISION,
                trust_remote_code=True,
            )
            .eval()
            .to(self._device)
        )
        self._mean = torch.tensor(
            [0.485, 0.456, 0.406],
            device=self._device,
            dtype=torch.float32,
        ).view(1, 3, 1, 1)
        self._std = torch.tensor(
            [0.229, 0.224, 0.225],
            device=self._device,
            dtype=torch.float32,
        ).view(1, 3, 1, 1)

    @staticmethod
    def _prediction_tensor(output):
        if hasattr(output, "logits"):
            output = output.logits
        elif isinstance(output, dict):
            output = output.get(
                "logits",
                list(output.values())[-1],
            )
        if isinstance(output, (list, tuple)):
            output = output[-1]
        if isinstance(output, (list, tuple)):
            output = output[-1]
        return output

    def remove(self, image_bytes: bytes) -> bytes:
        from PIL import Image, UnidentifiedImageError

        started = time.perf_counter()
        LOGGER.info("inference phase=decode state=start")
        try:
            with Image.open(io.BytesIO(image_bytes)) as source:
                source.load()
                if source.size != (CANVAS_SIZE, CANVAS_SIZE):
                    raise ValueError(
                        f"Image dimensions must be {CANVAS_SIZE}x{CANVAS_SIZE}."
                    )
                image = source.convert("RGB")
        except UnidentifiedImageError as exc:
            raise ValueError("Payload is not a supported image.") from exc
        LOGGER.info(
            "inference phase=decode state=complete seconds=%.3f",
            time.perf_counter() - started,
        )

        phase_started = time.perf_counter()
        LOGGER.info("inference phase=host_to_device state=start")
        array = (
            self._np.asarray(image, dtype=self._np.float32)
            / 255.0
        )
        tensor = (
            self._torch.from_numpy(array)
            .permute(2, 0, 1)
            .unsqueeze(0)
            .to(self._device)
        )
        tensor = (tensor - self._mean) / self._std
        self._torch.cuda.synchronize(self._device)
        LOGGER.info(
            "inference phase=host_to_device state=complete seconds=%.3f",
            time.perf_counter() - phase_started,
        )

        phase_started = time.perf_counter()
        LOGGER.info("inference phase=forward state=start")
        with self._torch.inference_mode():
            prediction = self._prediction_tensor(
                self._model(tensor)
            ).sigmoid()
        self._torch.cuda.synchronize(self._device)
        LOGGER.info(
            "inference phase=forward state=complete seconds=%.3f",
            time.perf_counter() - phase_started,
        )

        phase_started = time.perf_counter()
        LOGGER.info("inference phase=encode state=start")
        prediction = (
            prediction
            .squeeze()
            .detach()
            .float()
            .cpu()
            .numpy()
        )
        prediction = self._np.clip(prediction, 0.0, 1.0)
        mask = Image.fromarray(
            (prediction * 255.0).round().astype("uint8"),
            mode="L",
        )
        if mask.size != (CANVAS_SIZE, CANVAS_SIZE):
            mask = mask.resize(
                (CANVAS_SIZE, CANVAS_SIZE),
                Image.Resampling.BILINEAR,
            )

        stream = io.BytesIO()
        mask.save(stream, format="PNG", optimize=False)
        LOGGER.info(
            "inference phase=encode state=complete seconds=%.3f total_seconds=%.3f",
            time.perf_counter() - phase_started,
            time.perf_counter() - started,
        )
        return stream.getvalue()


def _decode_image(value: str) -> bytes:
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(422, "Image payload is not valid base64.") from exc
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Decoded image is too large.")
    return data


def create_app(
    *,
    engine: InferenceEngine | None = None,
    engine_factory: Callable[[], InferenceEngine] | None = None,
    token: str | None = None,
) -> FastAPI:
    if engine is not None and engine_factory is not None:
        raise ValueError(
            "Provide engine or engine_factory, not both."
        )
    expected_token = token
    if expected_token is None:
        expected_token = os.environ.pop("BACKGROUND_STUDIO_WORKER_TOKEN", "")
    if not expected_token:
        raise RuntimeError("BACKGROUND_STUDIO_WORKER_TOKEN is required.")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="background-studio-cuda",
        )
        loop = asyncio.get_running_loop()
        factory = engine_factory or (
            (lambda: engine)
            if engine is not None
            else BiRefNetCudaEngine
        )
        try:
            app.state.cuda_executor = executor
            app.state.engine = await loop.run_in_executor(
                executor,
                factory,
            )
            yield
        finally:
            executor.shutdown(
                wait=True,
                cancel_futures=True,
            )

    app = FastAPI(
        title="Background Studio GPU Worker",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_bytes=MAX_REQUEST_BYTES,
    )

    @app.exception_handler(Exception)
    async def unhandled_error(_, __):
        return JSONResponse(
            {"detail": "Inference failed."},
            status_code=500,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    @app.post("/remove")
    async def remove(
        request: RemoveRequest,
        x_background_studio_token: str | None = Header(None),
    ):
        supplied = x_background_studio_token or ""
        if not supplied or not hmac.compare_digest(
            supplied,
            expected_token,
        ):
            raise HTTPException(401, "Unauthorized.")

        image_bytes = _decode_image(request.image_base64)
        try:
            mask_bytes = await asyncio.get_running_loop().run_in_executor(
                app.state.cuda_executor,
                app.state.engine.remove,
                image_bytes,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

        return {
            "mask_base64": base64.b64encode(mask_bytes).decode("ascii")
        }

    return app


app = create_app()
