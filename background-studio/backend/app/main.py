from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import math
import traceback
from contextlib import asynccontextmanager
from typing import Literal, NoReturn
from urllib.parse import quote

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, validator
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings
from .images import (
    MAX_STROKE_POINTS,
    MAX_STROKE_RADIUS,
    MIN_STROKE_POINTS,
    MIN_STROKE_RADIUS,
    ImageValidationError,
    MaskStroke,
    apply_strokes,
    compose,
    decode_upload,
    derive_alpha,
    encode_image,
    make_preview,
    normalize_mask,
    parse_background,
    probe_upload,
)
from .remover import (
    InferenceService,
    Remover,
)
from .runpod_remover import build_default_remover
from .store import (
    JobNotFound,
    JobPending,
    JobStore,
    JobTerminal,
    StoreCapacityError,
    StoreCreationError,
    StoreDeletionError,
    StrokeLimitError,
    normalize_job_id,
)


class RenderLeaseResponse(Response):
    """Hold transient render memory until ASGI transmission terminates."""

    _CHUNK_SIZE = 64 * 1024

    def __init__(self, *args, store: JobStore, lease_id: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._store = store
        self._lease_id = lease_id

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await send({
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            })
            body = self.body
            if not body:
                await send({"type": "http.response.body", "body": b"", "more_body": False})
            else:
                offset = 0
                while offset < len(body):
                    end = min(offset + self._CHUNK_SIZE, len(body))
                    await send({
                        "type": "http.response.body",
                        "body": body[offset:end],
                        "more_body": end < len(body),
                    })
                    offset = end
        finally:
            lease_id = self._lease_id
            self._lease_id = None
            if lease_id is not None:
                self._store.release_render(lease_id)

        if self.background is not None:
            await self.background()


def _release_abandoned_render_worker(task, store: JobStore, lease_id: str) -> None:
    with contextlib.suppress(BaseException):
        task.result()
    with contextlib.suppress(BaseException):
        store.release_render(lease_id)


async def _await_render_worker(task, store: JobStore, lease_id: str):
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        task.add_done_callback(
            lambda completed: _release_abandoned_render_worker(
                completed, store, lease_id,
            )
        )
        raise
    except BaseException:
        store.release_render(lease_id)
        raise


class StrokeRequest(BaseModel):
    mode: Literal["remove", "restore"]
    radius: float = Field(
        ge=MIN_STROKE_RADIUS,
        le=MAX_STROKE_RADIUS,
    )
    softness: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
    )
    points: list[tuple[float, float]]

    class Config:
        extra = "forbid"

    @validator(
        "radius",
        "softness",
        pre=True,
    )
    def validate_number(cls, value):
        if (
            isinstance(value, bool)
            or not isinstance(
                value,
                (int, float),
            )
            or not math.isfinite(
                float(value)
            )
        ):
            raise ValueError(
                "must be a finite number"
            )

        return float(value)

    @validator(
        "points",
        pre=True,
    )
    def validate_points(cls, value):
        if (
            not isinstance(value, list)
            or not (
                MIN_STROKE_POINTS
                <= len(value)
                <= MAX_STROKE_POINTS
            )
        ):
            raise ValueError(
                "points must contain between "
                f"{MIN_STROKE_POINTS} and "
                f"{MAX_STROKE_POINTS} coordinates"
            )

        normalized: list[
            tuple[float, float]
        ] = []

        for point in value:
            if (
                not isinstance(
                    point,
                    (list, tuple),
                )
                or len(point) != 2
            ):
                raise ValueError(
                    "each point must be an [x, y] pair"
                )

            coordinates: list[float] = []

            for coordinate in point:
                if (
                    isinstance(coordinate, bool)
                    or not isinstance(
                        coordinate,
                        (int, float),
                    )
                    or not math.isfinite(
                        float(coordinate)
                    )
                    or not (
                        0.0
                        <= float(coordinate)
                        <= 1.0
                    )
                ):
                    raise ValueError(
                        "point coordinates must be "
                        "finite numbers between 0 and 1"
                    )

                coordinates.append(
                    float(coordinate)
                )

            normalized.append(
                (
                    coordinates[0],
                    coordinates[1],
                )
            )

        return normalized


class LoopbackOnlyMiddleware:
    """Enforce the loopback boundary without buffering response bodies."""

    SECURITY_HEADERS = (
        (b"cache-control", b"no-store"),
        (b"x-content-type-options", b"nosniff"),
        (b"referrer-policy", b"no-referrer"),
    )

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    @staticmethod
    def _host_part(value: str) -> str:
        value = value.strip().lower()

        if value.startswith("[") and "]" in value:
            return value[1:value.index("]")]

        if value.count(":") == 1:
            host, port = value.rsplit(":", 1)
            if port.isdigit():
                return host

        return value

    @classmethod
    def _is_loopback(cls, value: str) -> bool:
        host = cls._host_part(value)

        if host == "localhost":
            return True

        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        client_address = scope.get("client")
        client = client_address[0] if client_address else ""
        host = next(
            (
                value.decode("latin-1")
                for name, value in scope.get("headers", [])
                if name.lower() == b"host"
            ),
            "",
        )

        if not self._is_loopback(client) or not self._is_loopback(host):
            response = JSONResponse(
                {
                    "detail": (
                        "Background Studio accepts "
                        "loopback requests only."
                    )
                },
                status_code=403,
                headers={
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                    "Referrer-Policy": "no-referrer",
                },
            )
            await response(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                security_names = {name for name, _ in self.SECURITY_HEADERS}
                response_headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() not in security_names
                ]
                message = {
                    **message,
                    "headers": [*response_headers, *self.SECURITY_HEADERS],
                }
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


class RequestBodyLimitMiddleware:
    """Bound and account complete HTTP bodies before multipart parsing."""

    PARSER_SPOOL_MEMORY_THRESHOLD = 1024 * 1024

    def __init__(self, app: ASGIApp, max_bytes: int, store: JobStore | None = None) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.store = store

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        declared = 0
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                declared = 0
            if declared > self.max_bytes:
                await self._drain(receive, self.max_bytes)
                await self._reject(scope, send)
                return

        body_lease = None
        if self.store is not None:
            try:
                body_lease = self.store.reserve_body(declared)
            except StoreCapacityError as exc:
                await self._capacity_reject(scope, send, exc)
                return

        try:
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
                    if message.get("more_body", False):
                        await self._drain(receive, self.max_bytes)
                    await self._reject(scope, send)
                    return
                if body_lease is not None:
                    try:
                        self.store.resize_body(body_lease.id, max(declared, total))
                    except StoreCapacityError as exc:
                        await self._capacity_reject(scope, send, exc)
                        return
                if not message.get("more_body", False):
                    break

            if body_lease is not None:
                assert self.store is not None
                self.store.resize_body(body_lease.id, total)
                try:
                    self.store.reserve_parser_spool(
                        body_lease.id,
                        total,
                        self.PARSER_SPOOL_MEMORY_THRESHOLD,
                    )
                except StoreCapacityError as exc:
                    await self._capacity_reject(scope, send, exc)
                    return
                scope.setdefault("state", {})["body_lease_id"] = body_lease.id

            index = 0

            async def replay() -> Message:
                nonlocal index
                if index < len(messages):
                    message = messages[index]
                    index += 1
                    return message
                return {"type": "http.request", "body": b"", "more_body": False}

            await self.app(scope, replay, send)
        finally:
            if body_lease is not None:
                self.store.release_body(body_lease.id)

    @staticmethod
    async def _drain(receive: Receive, max_bytes: int) -> None:
        drained = 0
        # Best effort only: never let a slow or endless sender hold the 413.
        for _ in range(64):
            try:
                message = await asyncio.wait_for(receive(), timeout=0.05)
            except asyncio.TimeoutError:
                return
            if message["type"] == "http.disconnect":
                return
            if message["type"] == "http.request":
                drained += len(message.get("body", b""))
                if not message.get("more_body", False) or drained > max_bytes:
                    return

    async def _reject(self, scope: Scope, send: Send) -> None:
        response = JSONResponse(
            {"detail": f"Request bodies are limited to {self.max_bytes:,} bytes."},
            status_code=413,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )
        await response(scope, self._empty_receive, send)

    async def _capacity_reject(self, scope: Scope, send: Send, detail: StoreCapacityError) -> None:
        response = _capacity_response(
            detail,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )
        await response(scope, self._empty_receive, send)

    @staticmethod
    async def _empty_receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}


async def _read_limited(
    upload: UploadFile,
    limit: int,
) -> bytes:
    try:
        data = await upload.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(
                413,
                f"Uploads are limited to {limit:,} bytes.",
            )
        return data
    finally:
        await upload.close()


def _raise_job_http(exc: Exception) -> NoReturn:
    if isinstance(exc, JobPending):
        raise HTTPException(
            202,
            detail={"state": "creating", "message": "Job creation is still in progress."},
            headers={"Retry-After": "1"},
        ) from exc
    if isinstance(exc, JobTerminal):
        raise HTTPException(
            410,
            detail={"state": exc.state, "message": "Job is terminal."},
        ) from exc
    if isinstance(exc, JobNotFound):
        raise HTTPException(404, "Job not found or expired.") from exc
    raise exc


def _job_images(
    store: JobStore,
    job_id: str,
):
    try:
        return store.read_images(job_id)
    except (JobPending, JobTerminal, JobNotFound) as exc:
        _raise_job_http(exc)


def _job_render_data(
    store: JobStore,
    job_id: str,
):
    try:
        return store.read_render_data(job_id)
    except (JobPending, JobTerminal, JobNotFound) as exc:
        _raise_job_http(exc)


def _reserve_render(store: JobStore, job_id: str, operation):
    try:
        return store.reserve_render(job_id, operation)
    except (JobPending, JobTerminal, JobNotFound) as exc:
        _raise_job_http(exc)
    except ValueError as exc:
        raise HTTPException(404, "Job not found or expired.") from exc
    except StoreCapacityError:
        raise


def _render(
    store: JobStore,
    job_id: str,
    threshold: float,
    feather: float,
    background: str,
    max_side: int | None = None,
):
    try:
        parse_background(background)
        original, raw_mask, strokes = (
            _job_render_data(
                store,
                job_id,
            )
        )

        if max_side is not None:
            original_size = original.size
            original = make_preview(
                original,
                max_side,
            )
            raw_mask = make_preview(
                raw_mask,
                max_side,
            )
            feather *= min(
                original.width / original_size[0],
                original.height / original_size[1],
            )

        alpha = derive_alpha(
            raw_mask,
            threshold,
            feather,
        )
        alpha = apply_strokes(
            alpha,
            strokes,
            original,
        )

        return compose(
            original,
            alpha,
            background,
        )
    except ValueError as exc:
        raise HTTPException(
            422,
            str(exc),
        ) from exc


def _stroke_result(
    store: JobStore,
    operation,
    job_id: str,
    *args,
):
    try:
        revision, count = operation(
            job_id,
            *args,
        )
    except (JobPending, JobTerminal, JobNotFound) as exc:
        _raise_job_http(exc)
    except StrokeLimitError as exc:
        raise HTTPException(
            422,
            str(exc),
        ) from exc

    return {
        "revision": revision,
        "count": count,
    }


class GenerationFailure(RuntimeError):
    """Lightweight generation error that does not retain worker traceback frames."""

    def __init__(self, classification: str, message: str, cause: str = "capacity") -> None:
        self.classification = classification
        self.cause = cause
        super().__init__(message)


class GenerationCancelled(asyncio.CancelledError):
    classification = "cancelled"


CAPACITY_CAUSES = {
    "capacity",
    "disk_quota",
    "live_capacity",
    "memory_quota",
    "terminal_registry",
}


def _capacity_response(error: BaseException | str, headers=None, cause: str | None = None) -> JSONResponse:
    detail = error if isinstance(error, str) else str(error)
    structured_cause = cause or getattr(error, "cause", "capacity")
    if structured_cause not in CAPACITY_CAUSES:
        structured_cause = "capacity"
    return JSONResponse(
        {"detail": detail, "cause": structured_cause},
        status_code=507,
        headers=headers,
    )



def _generation_failure_classification(exc: BaseException) -> str:
    if isinstance(exc, asyncio.CancelledError):
        return "cancelled"
    if isinstance(exc, StoreCreationError):
        return exc.classification
    if isinstance(exc, ImageValidationError):
        return "image_validation"
    if isinstance(exc, StoreCapacityError):
        return "capacity"
    if isinstance(exc, JobTerminal):
        return "terminal"
    if isinstance(exc, StoreDeletionError):
        return "cleanup"
    return "generation"


def _raise_generation_failure(classification: str, message: str, cause: str = "capacity") -> NoReturn:
    if classification == "cancelled":
        raise GenerationCancelled(message) from None
    raise GenerationFailure(classification, message, cause) from None


def _generate_job(
    store: JobStore,
    inference: InferenceService,
    config: Settings,
    data: bytes,
    job_id: str,
    generation: str,
):
    original = None
    raw_mask = None

    def generation_is_valid() -> bool:
        lifecycle = store.lifecycle(job_id)
        return (
            lifecycle is not None
            and lifecycle.state == "creating"
            and lifecycle.generation == generation
        )

    try:
        width, height = probe_upload(data, config.max_pixels)
        store.reserve_resources(job_id, generation, len(data), width, height)
        original = decode_upload(data, config.max_pixels)
        if isinstance(inference, InferenceService):
            raw_mask = inference.remove(
                original.copy(),
                generation_is_valid=generation_is_valid,
            )
        else:
            raw_mask = inference.remove(original.copy())
        raw_mask = normalize_mask(raw_mask, original.size)
        job = store.create(original, raw_mask, job_id, generation)
    except BaseException as exc:
        classification = _generation_failure_classification(exc)
        cause = getattr(exc, "cause", "capacity")
        message = str(exc) or type(exc).__name__
        caught_traceback = exc.__traceback__
        with contextlib.suppress(RuntimeError):
            if caught_traceback is not None:
                traceback.clear_frames(caught_traceback)
        exc.__traceback__ = None
        del caught_traceback, exc
        del data, original, raw_mask
        try:
            store.finalize_creation(job_id, generation, message)
        except BaseException as cleanup_exc:
            classification = _generation_failure_classification(cleanup_exc)
            cause = getattr(cleanup_exc, "cause", "capacity")
            message = str(cleanup_exc) or type(cleanup_exc).__name__
            cleanup_traceback = cleanup_exc.__traceback__
            with contextlib.suppress(RuntimeError):
                if cleanup_traceback is not None:
                    traceback.clear_frames(cleanup_traceback)
            cleanup_exc.__traceback__ = None
            del cleanup_traceback, cleanup_exc
        _raise_generation_failure(classification, message, cause)

    del data, original, raw_mask
    store.release_worker_memory(job_id, generation)
    return job


def create_app(
    settings: Settings | None = None,
    remover: Remover | None = None,
) -> FastAPI:
    config = settings or Settings.from_env()
    store = JobStore(config)
    inference = InferenceService(
        remover or build_default_remover(config)
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await run_in_threadpool(store.startup)

        async def reap() -> None:
            while True:
                await asyncio.sleep(
                    config.cleanup_interval_seconds
                )
                await run_in_threadpool(
                    store.cleanup_expired
                )

        task = asyncio.create_task(reap())

        try:
            yield
        finally:
            task.cancel()

            try:
                with contextlib.suppress(
                    asyncio.CancelledError
                ):
                    await task
            finally:
                await run_in_threadpool(
                    store.shutdown
                )

    app = FastAPI(
        title="Background Studio",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    app.state.settings = config
    app.state.store = store
    app.state.inference = inference

    @app.exception_handler(StoreCapacityError)
    async def capacity_error_handler(_, exc: StoreCapacityError):
        return _capacity_response(exc)

    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_bytes=config.max_upload_bytes + config.request_overhead_bytes,
        store=store,
    )

    if config.enforce_loopback:
        app.add_middleware(
            LoopbackOnlyMiddleware
        )

    @app.get("/api/health")
    async def health():
        jobs, disk_bytes = store.stats()
        return {
            "ok": True,
            "jobs": jobs,
            "disk_bytes": disk_bytes,
        }

    @app.post(
        "/api/jobs",
        status_code=201,
    )
    async def create_job(
        request: Request,
        file: UploadFile = File(...),
        job_id: str | None = Form(None),
    ):
        reservation = asyncio.create_task(run_in_threadpool(store.reserve, job_id))
        try:
            job_id, owner, lifecycle, generation = await asyncio.shield(reservation)
        except asyncio.CancelledError:
            try:
                reserved_job_id, reserved_owner, _, reserved_generation = await reservation
            except Exception:
                pass
            else:
                if reserved_owner and reserved_generation is not None:
                    try:
                        await run_in_threadpool(
                            store.cancel_generation,
                            reserved_job_id,
                            reserved_generation,
                        )
                        await run_in_threadpool(
                            store.finalize_creation,
                            reserved_job_id,
                            reserved_generation,
                            "Request was cancelled during reservation.",
                        )
                    except Exception:
                        # Cancellation remains authoritative; the exact lease is
                        # still tracked if cleanup must be reconciled later.
                        pass
            with contextlib.suppress(Exception):
                await file.close()
            raise
        except ValueError as exc:
            await file.close()
            raise HTTPException(422, str(exc)) from exc
        except StoreCapacityError as exc:
            await file.close()
            return _capacity_response(exc)

        if not owner:
            await file.close()
            if lifecycle.state == "live" and lifecycle.job is not None:
                existing = lifecycle.job
                return {"id": existing.id, "width": existing.width, "height": existing.height}
            if lifecycle.state == "creating":
                return JSONResponse(
                    {"id": job_id, "state": "creating"},
                    status_code=202,
                    headers={"Retry-After": "1"},
                )
            raise HTTPException(
                410,
                detail={"state": lifecycle.state, "message": "Job creation is terminal."},
            )

        assert generation is not None
        handed_to_worker = False
        try:
            upload_size = file.size if file.size is not None else config.max_upload_bytes + 1
            if file.size is not None and upload_size > config.max_upload_bytes:
                raise HTTPException(413, f"Uploads are limited to {config.max_upload_bytes:,} bytes.")
            store.reserve_upload_copy(job_id, generation, upload_size)
            data = await _read_limited(
                file,
                config.max_upload_bytes,
            )
            store.reserve_upload_copy(job_id, generation, len(data))
            body_lease_id = request.scope.get("state", {}).get("body_lease_id")
            if body_lease_id is None:
                raise StoreCapacityError("The request body reservation is missing.")

            worker = asyncio.create_task(run_in_threadpool(
                _generate_job,
                store,
                inference,
                config,
                data,
                job_id,
                generation,
            ))
            handed_to_worker = True
            job = await asyncio.shield(worker)
        except GenerationFailure as exc:
            if exc.classification == "image_validation":
                raise HTTPException(415, str(exc)) from None
            if exc.classification == "capacity":
                return _capacity_response(exc)
            if exc.classification == "terminal":
                lifecycle = store.lifecycle(job_id)
                state = lifecycle.state if lifecycle is not None else "tombstoned"
                raise HTTPException(
                    410,
                    detail={"state": state, "message": "Job creation was cancelled."},
                ) from None
            if exc.classification == "cleanup":
                raise HTTPException(500, str(exc)) from None
            raise HTTPException(
                500,
                f"Background removal failed: {exc}",
            ) from None
        except ImageValidationError as exc:
            raise HTTPException(
                415,
                str(exc),
            ) from exc
        except StoreCapacityError as exc:
            return _capacity_response(exc)
        except HTTPException:
            raise
        except JobTerminal as exc:
            raise HTTPException(
                410,
                detail={"state": exc.state, "message": "Job creation was cancelled."},
            ) from exc
        except StoreDeletionError as exc:
            raise HTTPException(500, str(exc)) from exc
        except asyncio.CancelledError:
            store.cancel_generation(job_id, generation)
            raise
        except Exception as exc:
            raise HTTPException(
                500,
                f"Background removal failed: {exc}",
            ) from exc
        finally:
            if not handed_to_worker:
                await run_in_threadpool(store.finalize_creation, job_id, generation, "Upload failed.")

        return {
            "id": job.id,
            "width": job.width,
            "height": job.height,
        }

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str):
        try:
            job_id = normalize_job_id(job_id)
        except ValueError as exc:
            raise HTTPException(404, "Job not found or expired.") from exc
        lifecycle = await run_in_threadpool(store.lifecycle, job_id)
        if lifecycle is None:
            return JSONResponse({"id": job_id, "state": "unknown"}, status_code=404)
        if lifecycle.state == "creating":
            return JSONResponse(
                {"id": job_id, "state": "creating"},
                status_code=202,
                headers={"Retry-After": "1"},
            )
        if lifecycle.state in ("failed", "tombstoned"):
            return JSONResponse(
                {"id": job_id, "state": lifecycle.state},
                status_code=410,
            )
        job = lifecycle.job
        if job is None:
            return JSONResponse({"id": job_id, "state": "unknown"}, status_code=404)
        return {"id": job.id, "width": job.width, "height": job.height}

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str):
        try:
            job_id = normalize_job_id(job_id)
        except ValueError as exc:
            raise HTTPException(404, "Job not found or expired.") from exc
        try:
            complete = await run_in_threadpool(store.cancel, job_id)
        except StoreCapacityError as exc:
            return _capacity_response(exc)
        if complete:
            return Response(status_code=204)
        return JSONResponse(
            {"id": job_id, "state": "cleanup_pending"},
            status_code=202,
            headers={"Retry-After": "1"},
        )

    @app.post("/api/jobs/{job_id}/touch")
    async def touch_job(job_id: str):
        try:
            job_id = normalize_job_id(job_id)
        except ValueError as exc:
            raise HTTPException(404, "Job not found or expired.") from exc
        try:
            await run_in_threadpool(store.touch, job_id)
        except JobNotFound:
            return JSONResponse(
                {"id": job_id, "state": "unknown"},
                status_code=404,
            )
        except JobPending:
            return JSONResponse(
                {"id": job_id, "state": "creating"},
                status_code=202,
                headers={"Retry-After": "1"},
            )
        except JobTerminal as exc:
            return JSONResponse(
                {"id": job_id, "state": exc.state},
                status_code=410,
            )
        return Response(status_code=204)

    @app.post(
        "/api/jobs/{job_id}/strokes"
    )
    async def append_stroke(
        job_id: str,
        stroke: StrokeRequest,
    ):
        stored_stroke = MaskStroke(
            mode=stroke.mode,
            radius=stroke.radius,
            softness=stroke.softness,
            points=tuple(stroke.points),
        )

        return await run_in_threadpool(
            _stroke_result,
            store,
            store.append_stroke,
            job_id,
            stored_stroke,
        )

    @app.delete(
        "/api/jobs/{job_id}/strokes/last"
    )
    async def undo_stroke(job_id: str):
        return await run_in_threadpool(
            _stroke_result,
            store,
            store.undo_stroke,
            job_id,
        )

    @app.delete(
        "/api/jobs/{job_id}/strokes"
    )
    async def reset_strokes(job_id: str):
        return await run_in_threadpool(
            _stroke_result,
            store,
            store.reset_strokes,
            job_id,
        )

    @app.get(
        "/api/jobs/{job_id}/original"
    )
    async def original(job_id: str):
        lease = _reserve_render(store, job_id, "original")

        def work():
            original_image, _ = _job_images(store, job_id)
            data, media_type, _ = encode_image(original_image, "png")
            return data, media_type

        worker = asyncio.create_task(run_in_threadpool(work))
        data, media_type = await _await_render_worker(worker, store, lease.id)
        try:
            return RenderLeaseResponse(
                data, media_type=media_type, store=store, lease_id=lease.id,
            )
        except BaseException:
            store.release_render(lease.id)
            raise

    @app.get(
        "/api/jobs/{job_id}/preview"
    )
    async def preview(
        job_id: str,
        revision: int = Query(0, ge=0),
        threshold: float = Query(
            0.0,
            ge=0.0,
            le=1.0,
        ),
        feather: float = Query(
            0.0,
            ge=0.0,
            le=64.0,
        ),
        background: str = Query(
            "transparent"
        ),
    ):
        lease = _reserve_render(store, job_id, "preview")

        def work():
            rendered = _render(
                store, job_id, threshold, feather, background,
                config.preview_max_side,
            )
            data, media_type, _ = encode_image(rendered, "png")
            return data, media_type

        worker = asyncio.create_task(run_in_threadpool(work))
        data, media_type = await _await_render_worker(worker, store, lease.id)
        try:
            return RenderLeaseResponse(
                data, media_type=media_type, headers={"Cache-Control": "no-store"},
                store=store, lease_id=lease.id,
            )
        except BaseException:
            store.release_render(lease.id)
            raise

    @app.get(
        "/api/jobs/{job_id}/export"
    )
    async def export(
        job_id: str,
        threshold: float = Query(
            0.0,
            ge=0.0,
            le=1.0,
        ),
        feather: float = Query(
            0.0,
            ge=0.0,
            le=64.0,
        ),
        background: str = Query(
            "transparent"
        ),
        format: str = Query(
            "png",
            pattern="^(png|jpeg|jpg)$",
        ),
    ):
        if (
            background == "transparent"
            and format != "png"
        ):
            raise HTTPException(
                422,
                "Transparent export must use PNG.",
            )

        lease = _reserve_render(store, job_id, "export")

        def work():
            rendered = _render(
                store, job_id, threshold, feather, background,
            )
            return encode_image(rendered, format)

        worker = asyncio.create_task(run_in_threadpool(work))
        data, media_type, filename = await _await_render_worker(
            worker, store, lease.id,
        )
        disposition = "attachment; filename*=UTF-8''" f"{quote(filename)}"
        try:
            return RenderLeaseResponse(
                data, media_type=media_type,
                headers={"Content-Disposition": disposition},
                store=store, lease_id=lease.id,
            )
        except BaseException:
            store.release_render(lease.id)
            raise

    @app.delete(
        "/api/jobs/{job_id}",
        status_code=204,
    )
    async def delete_job(job_id: str):
        try:
            deleted = await run_in_threadpool(store.delete, job_id)
        except ValueError as exc:
            raise HTTPException(404, "Job not found or expired.") from exc
        except (JobPending, JobTerminal, JobNotFound) as exc:
            _raise_job_http(exc)
        except StoreDeletionError as exc:
            raise HTTPException(500, str(exc)) from exc

        if not deleted:
            raise HTTPException(
                410,
                "Job is already terminal.",
            )

        return Response(status_code=204)

    return app


app = create_app()
