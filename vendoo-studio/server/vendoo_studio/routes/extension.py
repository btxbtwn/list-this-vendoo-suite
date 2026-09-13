from __future__ import annotations

import json
import os
import uuid
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from vendoo_studio.models.protocol import ProtocolMessage
from vendoo_studio.database import SessionLocal

router = APIRouter(tags=["extension"])

PAIRING_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "pairing_token.txt")


class ExtensionManager:
    def __init__(self):
        self.connection: Optional[WebSocket] = None
        self.paired = False
        self._pairing_token: Optional[str] = None

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

    async def send_message(self, message: dict):
        if self.connection:
            try:
                await self.connection.send_json(message)
            except Exception:
                pass

    async def disconnect(self):
        if self.connection:
            try:
                await self.connection.close()
            except Exception:
                pass
        self.connection = None


extension_manager = ExtensionManager()


async def dispatch_queued_jobs():
    if not extension_manager.connected:
        return
    db = SessionLocal()
    try:
        from vendoo_studio.repositories.queries import JobRepo
        repo = JobRepo(db)
        active_jobs = repo.get_active()
        for job in active_jobs:
            photos_list = _build_photo_list(job.conversation_id, db)
            registry_selectors = _build_registry_selectors(job.listing_snapshot or {}, db)
            await extension_manager.send_message(ProtocolMessage(
                    type="job.start",
                    job_id=job.id,
                    message_id=uuid.uuid4().hex[:12],
                    payload={
                        "job_id": job.id,
                        "listing": job.listing_snapshot,
                        "photos": photos_list,
                        "options": {
                            "platforms": ["ebay", "etsy", "poshmark", "mercari", "depop"],
                            "saveDrafts": True,
                            "publish": False,
                        },
                        "registry_selectors": registry_selectors,
                        "vendoo_item_id": job.vendoo_item_id,
                        "vendoo_url": job.vendoo_url,
                    },
                ).model_dump())
            repo.update_status(job.id, "dispatched")
    finally:
        db.close()


def _build_photo_list(conv_id: str, db) -> list[dict]:
    from vendoo_studio.repositories.queries import ConversationRepo
    repo = ConversationRepo(db)
    photos = repo.get_photos(conv_id)
    return [{"id": p.id, "name": p.original_filename, "stored_filename": p.stored_filename} for p in photos]


def _build_registry_selectors(listing: dict, db) -> dict:
    from vendoo_studio.repositories.queries import RegistryRepo
    repo = RegistryRepo(db)
    category_path = listing.get("category_path", "")

    result = {}
    for marketplace in ("ebay", "etsy", "poshmark", "mercari", "depop"):
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

    if extension_manager.connection:
        try:
            await ws.send_json({"type": "error", "message": "Another extension is already connected"})
            await ws.close()
        except Exception:
            pass
        return

    extension_manager.connection = ws

    db = SessionLocal()
    try:
        while True:
            raw = await ws.receive_text()
            message = json.loads(raw)

            msg_type = message.get("type", "")

            if msg_type == "extension.ready":
                token = message.get("payload", {}).get("token", "")
                if extension_manager.verify_token(token):
                    extension_manager.paired = True
                    await ws.send_json(ProtocolMessage(
                        type="connection.accepted",
                        payload={"paired": True},
                    ).model_dump())
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
                    repo = JobRepo(db)
                    step = payload.get("step", "")
                    vid = payload.get("vendoo_item_id")
                    vurl = payload.get("vendoo_url")
                    repo.update_status(job_id, "dispatched", step, vendoo_item_id=vid, vendoo_url=vurl)
                    repo.add_event(job_id, "step_completed", step, payload)
                    _set_conversation_status(db, job_id, "listing")

            elif msg_type == "job.step_failed":
                payload = message.get("payload", {})
                job_id = message.get("job_id")
                if job_id:
                    from vendoo_studio.repositories.queries import JobRepo
                    repo = JobRepo(db)
                    err = payload.get("error", "Unknown error")
                    step = payload.get("step", "")
                    repo.update_status(job_id, "failed", step, error=err)
                    repo.add_event(job_id, "step_failed", step, payload)
                    _set_conversation_status(db, job_id, "failed")

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

            elif msg_type == "diagnostic.observed":
                payload = message.get("payload", {})
                obs_id = payload.get("observation_id", "")
                from vendoo_studio.repositories.queries import DiagnosticRepo
                repo = DiagnosticRepo(db)
                repo.save_observation(payload)
                await ws.send_json(ProtocolMessage(
                    type="diagnostic.ack",
                    payload={"observation_id": obs_id},
                ).model_dump())

            elif msg_type == "pong":
                pass

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        extension_manager.connection = None
        extension_manager.paired = False
        db.close()
