from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from vendoo_studio.config import PAIRING_FILE
from vendoo_studio.models.protocol import ProtocolMessage
from vendoo_studio.database import SessionLocal
from vendoo_studio.services.chrome_bridge import (
    ChromeBridgeError,
    clear_extension_reload_pending,
    install_bundled_extension,
    mark_extension_reload_pending,
    needs_worker_reload,
    pending_extension_reload_token,
)

router = APIRouter(tags=["extension"])

VENDOO_GET_TIMEOUT_SEC = 30


class ExtensionManager:
    def __init__(self):
        self.connection: Optional[WebSocket] = None
        self.paired = False
        self._pairing_token: Optional[str] = None
        self._waits: dict[str, asyncio.Future] = {}

    def register_wait(self, request_id: str) -> asyncio.Future:
        self.cancel_wait(request_id)
        fut = asyncio.get_running_loop().create_future()
        self._waits[request_id] = fut
        return fut

    def resolve_wait(self, request_id: str, payload: dict) -> None:
        fut = self._waits.pop(request_id, None)
        if fut and not fut.done():
            fut.set_result(payload)

    def cancel_wait(self, request_id: str) -> None:
        fut = self._waits.pop(request_id, None)
        if fut and not fut.done():
            fut.cancel()

    @property
    def connected(self) -> bool:
        return self.connection is not None and self.paired

    def get_persistent_token(self) -> str | None:
        try:
            with open(PAIRING_FILE) as f:
                return f.read().strip() or None
        except FileNotFoundError:
            return None

    def save_persistent_token(self, token: str):
        os.makedirs(os.path.dirname(PAIRING_FILE), exist_ok=True)
        with open(PAIRING_FILE, "w") as f:
            f.write(token)

    def generate_pairing_token(self) -> str:
        existing = self.get_persistent_token()
        if existing:
            self._pairing_token = existing
            return existing
        self._pairing_token = uuid.uuid4().hex[:8]
        self.save_persistent_token(self._pairing_token)
        return self._pairing_token

    def verify_token(self, token: str) -> bool:
        persisted = self.get_persistent_token()
        if persisted and persisted == token:
            return True
        if self._pairing_token and self._pairing_token == token:
            return True
        return token == "direct"

    async def send_message(self, message: dict) -> bool:
        connection = self.connection
        if not connection:
            return False
        try:
            await connection.send_json(message)
            return True
        except Exception:
            if self.connection is connection:
                self.connection = None
                self.paired = False
            return False

    async def disconnect(self, ws: WebSocket | None = None):
        connection = self.connection if ws is None else ws
        if connection is None:
            if ws is None:
                self.connection = None
                self.paired = False
            return
        try:
            await connection.close()
        except Exception:
            pass
        if self.connection is connection:
            self.connection = None
            self.paired = False


extension_manager = ExtensionManager()


def _reported_reload_generation(payload: dict) -> str | None:
    reported = payload.get("reload_generation")
    if reported is None:
        return None
    token = str(reported).strip()
    return token or None


async def request_extension_reload(generation: str) -> bool:
    return await extension_manager.send_message(ProtocolMessage(
        type="extension.reload",
        payload={"generation": generation},
    ).model_dump(mode="json"))


async def handshake_extension(ws: WebSocket, reported_generation: str | None) -> bool:
    try:
        files_changed = install_bundled_extension()
    except ChromeBridgeError:
        files_changed = False
    pending = pending_extension_reload_token()
    if needs_worker_reload(pending, reported_generation, files_changed):
        token = pending or mark_extension_reload_pending()
        await ws.send_json(ProtocolMessage(
            type="extension.reload",
            payload={"generation": token},
        ).model_dump(mode="json"))
        return False
    if pending:
        clear_extension_reload_pending()
    await ws.send_json(ProtocolMessage(
        type="connection.accepted",
        payload={"paired": True},
    ).model_dump(mode="json"))
    return True


async def dispatch_queued_jobs():
    db = SessionLocal()
    try:
        from vendoo_studio.repositories.queries import JobRepo
        repo = JobRepo(db)
        jobs = repo.get_dispatchable()
        if not jobs:
            return
        if not extension_manager.connected:
            for job in jobs:
                if job.status != "awaiting_extension":
                    repo.update_status(job.id, "awaiting_extension", "awaiting_extension")
            return
        job = jobs[0]
        photos_list = _build_photo_list(job.conversation_id, db)
        registry_selectors = _build_registry_selectors(job.listing_snapshot or {}, db)
        from vendoo_studio.repositories.queries import ConversationRepo
        from vendoo_studio.services.marketplaces import selected_fillable_platforms
        from vendoo_studio.services.vendoo_import import vendoo_binding
        conv = ConversationRepo(db).get(job.conversation_id)
        binding = vendoo_binding(conv.notes if conv else None)
        item_id = job.vendoo_item_id or binding.get("vendooItemId")
        item_url = job.vendoo_url or binding.get("vendooUrl")
        reuse_existing = bool(item_id or item_url)
        sent = await extension_manager.send_message(ProtocolMessage(
            type="job.start",
            job_id=job.id,
            message_id=uuid.uuid4().hex[:12],
            payload={
                "job_id": job.id,
                "listing": job.listing_snapshot,
                "photos": photos_list,
                "vendoo_item_id": item_id,
                "vendoo_url": item_url,
                "options": {
                    "platforms": selected_fillable_platforms(),
                    "saveDrafts": True,
                    "publish": False,
                    "reuseExistingItem": reuse_existing,
                    "skipPhotos": reuse_existing,
                    "clearBeforeFill": reuse_existing,
                    "vendoo_item_id": item_id,
                    "vendoo_url": item_url,
                },
                "registry_selectors": registry_selectors,
            },
        ).model_dump(mode="json"))
        if sent:
            repo.update_status(job.id, "dispatched")
        else:
            repo.update_status(job.id, "awaiting_extension", "awaiting_extension")
    finally:
        db.close()


async def dispatch_fill_fields(job, fields: list[dict]) -> bool:
    if not extension_manager.connected:
        return False
    return await extension_manager.send_message(ProtocolMessage(
        type="job.fill_fields",
        job_id=job.id,
        message_id=uuid.uuid4().hex[:12],
        payload={
            "job_id": job.id,
            "vendoo_item_id": job.vendoo_item_id,
            "vendoo_url": job.vendoo_url,
            "fields": fields,
        },
    ).model_dump(mode="json"))


async def dispatch_vendoo_get(job, request_id: str) -> bool:
    if not extension_manager.connected:
        return False
    return await extension_manager.send_message(ProtocolMessage(
        type="job.vendoo_get",
        job_id=job.id,
        message_id=request_id,
        payload={
            "job_id": job.id,
            "request_id": request_id,
            "vendoo_item_id": job.vendoo_item_id,
            "vendoo_url": job.vendoo_url,
        },
    ).model_dump(mode="json"))


async def dispatch_open_listing(job) -> bool:
    if not extension_manager.connected:
        return False
    return await extension_manager.send_message(ProtocolMessage(
        type="job.open_listing",
        job_id=job.id,
        message_id=uuid.uuid4().hex[:12],
        payload={
            "job_id": job.id,
            "vendoo_item_id": job.vendoo_item_id,
            "vendoo_url": job.vendoo_url,
        },
    ).model_dump(mode="json"))


def _build_photo_list(conv_id: str, db) -> list[dict]:
    from vendoo_studio.repositories.queries import ConversationRepo
    repo = ConversationRepo(db)
    photos = repo.get_photos(conv_id)
    return [{"id": p.id, "name": p.original_filename, "stored_filename": p.stored_filename} for p in photos]


def _build_registry_selectors(listing: dict, db) -> dict:
    from vendoo_studio.repositories.queries import RegistryRepo
    repo = RegistryRepo(db)
    category_path = listing.get("category_path", "")

    from vendoo_studio.services.marketplaces import selected_fillable_platforms

    result = {}
    for marketplace in selected_fillable_platforms():
        fields = {}
        specifics = listing.get(f"{marketplace}_specifics", {}) or {}
        if isinstance(specifics, dict):
            for field_label, value in specifics.items():
                selectors = repo.get_best_selectors(marketplace, field_label, category_path)
                if selectors:
                    fields[field_label] = {
                        "selectors": selectors,
                        "value": str(value) if value else "",
                    }
        result[marketplace] = fields

    general_fields = {}
    for field_label in ("title", "description", "brand", "tags", "sku", "condition"):
        selectors = repo.get_best_selectors("general", field_label, category_path)
        if selectors:
            general_fields[field_label] = {
                "selectors": selectors,
                "value": str(listing.get(field_label, "")),
            }
    if general_fields:
        result["general"] = general_fields

    return result


def _set_conversation_status(db, job_id: str, status: str) -> None:
    from vendoo_studio.repositories.queries import ConversationRepo, JobRepo
    job = JobRepo(db).get(job_id)
    if job:
        ConversationRepo(db).update_status(job.conversation_id, status)


@router.get("/api/extension/pairing-token")
def get_pairing_token():
    token = extension_manager.generate_pairing_token()
    return {"token": token}


@router.get("/api/extension/status")
def extension_status():
    return {
        "connected": extension_manager.connected,
        "paired": extension_manager.paired,
    }


@router.websocket("/api/extension/ws")
async def extension_websocket(ws: WebSocket):
    await ws.accept()

    old = extension_manager.connection
    if old is not None and old is not ws:
        extension_manager.connection = None
        extension_manager.paired = False
        try:
            await old.close()
        except Exception:
            pass

    extension_manager.connection = ws

    db = SessionLocal()
    try:
        while True:
            raw = await ws.receive_text()
            message = json.loads(raw)

            msg_type = message.get("type", "")

            if msg_type == "extension.ready":
                payload = message.get("payload", {}) or {}
                token = payload.get("token", "")
                if extension_manager.verify_token(token):
                    extension_manager.paired = True
                    accepted = await handshake_extension(ws, _reported_reload_generation(payload))
                    if accepted:
                        from vendoo_studio.repositories.queries import JobRepo
                        JobRepo(db).requeue_interrupted()
                        await dispatch_queued_jobs()
                else:
                    await ws.send_json({"type": "error", "message": "Invalid pairing token"})
                continue

            if not extension_manager.paired:
                await ws.send_json({"type": "error", "message": "Not paired"})
                continue

            if msg_type == "job.accepted":
                job_id = message.get("job_id")
                if job_id:
                    from vendoo_studio.repositories.queries import JobRepo
                    repo = JobRepo(db)
                    repo.update_status(job_id, "dispatched")
                    repo.add_event(job_id, "dispatched")
                    _set_conversation_status(db, job_id, "listing")

            elif msg_type == "job.progress":
                payload = message.get("payload", {})
                job_id = message.get("job_id")
                if job_id:
                    from vendoo_studio.repositories.queries import JobRepo
                    repo = JobRepo(db)
                    step = payload.get("step", "")
                    repo.update_status(job_id, "dispatched", step)
                    repo.add_event(job_id, "progress", step, payload)
                    _set_conversation_status(db, job_id, "listing")

            elif msg_type == "job.step_completed":
                payload = message.get("payload", {})
                job_id = message.get("job_id")
                if job_id:
                    from vendoo_studio.repositories.queries import JobRepo
                    from vendoo_studio.services.fill_log import FillLogService
                    repo = JobRepo(db)
                    step = payload.get("step", "")
                    vid = payload.get("vendoo_item_id")
                    vurl = payload.get("vendoo_url")
                    job = repo.get(job_id)
                    if step == "filling_fields":
                        repo.update_status(job_id, "completed", step, vendoo_item_id=vid, vendoo_url=vurl)
                        repo.add_event(job_id, "step_completed", step, payload)
                        job = repo.get(job_id)
                        if job and payload.get("fill_log"):
                            FillLogService(db).apply_field_results(job, payload.get("fill_log"))
                        _set_conversation_status(db, job_id, "completed")
                    else:
                        repo.update_status(job_id, "dispatched", step, vendoo_item_id=vid, vendoo_url=vurl)
                        repo.add_event(job_id, "step_completed", step, payload)
                        job = repo.get(job_id)
                        if job and payload.get("fill_log"):
                            FillLogService(db).save_step(job, step, payload.get("fill_log"))
                        _set_conversation_status(db, job_id, "listing")

            elif msg_type == "job.step_failed":
                payload = message.get("payload", {})
                job_id = message.get("job_id")
                if job_id:
                    from vendoo_studio.repositories.queries import JobRepo
                    from vendoo_studio.services.fill_log import FillLogService
                    repo = JobRepo(db)
                    err = payload.get("error", "Unknown error")
                    step = payload.get("step", "")
                    job = repo.get(job_id)
                    if step == "filling_fields":
                        restore = "completed" if (job and (job.vendoo_url or job.vendoo_item_id)) else "failed"
                        repo.update_status(job_id, restore, step, error=err)
                        repo.add_event(job_id, "step_failed", step, payload)
                        job = repo.get(job_id)
                        if job and payload.get("fill_log"):
                            FillLogService(db).apply_field_results(job, payload.get("fill_log"))
                        _set_conversation_status(db, job_id, restore)
                    else:
                        repo.update_status(job_id, "failed", step, error=err)
                        repo.add_event(job_id, "step_failed", step, payload)
                        job = repo.get(job_id)
                        if job and payload.get("fill_log"):
                            FillLogService(db).save_step(job, step, payload.get("fill_log"))
                        _set_conversation_status(db, job_id, "failed")

            elif msg_type == "job.vendoo_item":
                payload = message.get("payload") or {}
                request_id = payload.get("request_id") or message.get("message_id")
                if request_id:
                    extension_manager.resolve_wait(str(request_id), payload)
                job_id = message.get("job_id")
                if job_id:
                    from vendoo_studio.repositories.queries import JobRepo
                    repo = JobRepo(db)
                    repo.add_event(job_id, "vendoo_get", None, {
                        "ok": bool(payload.get("ok")),
                        "source": payload.get("source"),
                        "item_id": payload.get("item_id"),
                        "error": payload.get("error") or payload.get("api_error"),
                    })

            elif msg_type == "job.completed":
                job_id = message.get("job_id")
                if job_id:
                    from vendoo_studio.repositories.queries import JobRepo
                    repo = JobRepo(db)
                    vurl = message.get("payload", {}).get("vendoo_url", "")
                    repo.update_status(job_id, "completed", vendoo_url=vurl or None)
                    repo.add_event(job_id, "completed")
                    _set_conversation_status(db, job_id, "completed")

            elif msg_type == "job.cancelled":
                job_id = message.get("job_id")
                if job_id:
                    from vendoo_studio.repositories.queries import JobRepo
                    repo = JobRepo(db)
                    repo.update_status(job_id, "cancelled")
                    repo.add_event(job_id, "cancelled")
                    _set_conversation_status(db, job_id, "draft")

            elif msg_type == "job.preview_frame":
                job_id = message.get("job_id")
                if job_id:
                    from vendoo_studio.services.preview_hub import preview_hub, sanitize_frame
                    payload = message.get("payload") or {}
                    frame = sanitize_frame(payload, payload.get("step") or "")
                    if frame:
                        await preview_hub.publish(job_id, frame)

            elif msg_type == "diagnostic.observed":
                payload = message.get("payload", {})
                obs_id = payload.get("observation_id", "")
                from vendoo_studio.repositories.queries import DiagnosticRepo
                repo = DiagnosticRepo(db)
                repo.save_observation(payload)
                await ws.send_json(ProtocolMessage(
                    type="diagnostic.ack",
                    payload={"observation_id": obs_id},
                ).model_dump(mode="json"))

            elif msg_type == "pong":
                pass

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if extension_manager.connection is ws:
            extension_manager.connection = None
            extension_manager.paired = False
        db.close()
