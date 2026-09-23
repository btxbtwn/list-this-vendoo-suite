from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from vendoo_studio.config import PAIRING_FILE
from vendoo_studio.models.protocol import ProtocolMessage
from vendoo_studio.database import SessionLocal
from vendoo_studio.services.chrome_bridge import (
    ChromeBridgeError,
    clear_extension_reload_pending,
    extension_build_status,
    extension_reload_token_if_needed,
    install_bundled_extension,
    pending_extension_reload_token,
    relaunch_studio_chrome,
)

router = APIRouter(tags=["extension"])

log = logging.getLogger("vendoo_studio.extension")

VENDOO_GET_TIMEOUT_SEC = 120
ROUTE_ITEM_IDS = frozenset({"new", "edit", "create"})


async def _warm_label_catalog() -> None:
    """Refresh the on-disk id→name map once Chrome pairs.

    Failures are logged and ignored: handshake already succeeded, and Regenerate
    can still fall back to whatever the cache already holds.
    """
    try:
        from vendoo_studio.services.vendoo_create import LOOKUP_TIMEOUT_SEC, label_display_map

        await label_display_map(None, timeout=LOOKUP_TIMEOUT_SEC)
    except Exception:  # noqa: BLE001 - best-effort decoration
        log.warning("Vendoo label catalog warm skipped", exc_info=True)


def durable_vendoo_item_id(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower() in ROUTE_ITEM_IDS:
        return None
    return text


def _ws_origin_allowed(origin: str) -> bool:
    from vendoo_studio.config import CORS_ORIGINS

    value = (origin or "").strip()
    if not value:
        return False
    lowered = value.lower()
    if lowered.startswith("chrome-extension://"):
        return True
    return value in CORS_ORIGINS


def _websocket_allowed(ws: WebSocket) -> bool:
    origin = (ws.headers.get("origin") or "").strip()
    if _ws_origin_allowed(origin):
        return True
    host = (ws.client.host if ws.client else "") or ""
    return host in {"127.0.0.1", "::1", "localhost"} and not origin


class ExtensionManager:
    def __init__(self):
        self.connection: WebSocket | None = None
        self.paired = False
        self.version: str | None = None
        self.build: str | None = None
        self.reload_generation: str | None = None
        self._pairing_token: str | None = None
        self._waits: dict[str, asyncio.Future] = {}
        self._wait_jobs: dict[str, str] = {}

    def register_wait(self, request_id: str, job_id: str | None = None) -> asyncio.Future:
        self.cancel_wait(request_id)
        fut = asyncio.get_running_loop().create_future()
        self._waits[request_id] = fut
        if job_id:
            self._wait_jobs[request_id] = job_id
        return fut

    def resolve_wait(self, request_id: str, payload: dict) -> None:
        self._wait_jobs.pop(request_id, None)
        fut = self._waits.pop(request_id, None)
        if fut and not fut.done():
            fut.set_result(payload)

    def cancel_wait(self, request_id: str) -> None:
        self._wait_jobs.pop(request_id, None)
        fut = self._waits.pop(request_id, None)
        if fut and not fut.done():
            fut.cancel()

    def cancel_waits_for_job(self, job_id: str) -> None:
        for request_id, wait_job_id in list(self._wait_jobs.items()):
            if wait_job_id == job_id:
                self.cancel_wait(request_id)

    def _mark_disconnected(self) -> None:
        self.connection = None
        self.paired = False
        self.version = None
        self.build = None
        self.reload_generation = None

    @property
    def connected(self) -> bool:
        return self.connection is not None and self.paired

    def get_persistent_token(self) -> str | None:
        try:
            with open(PAIRING_FILE) as f:
                return f.read().strip() or None
        except FileNotFoundError:
            return None

    def generate_pairing_token(self) -> str:
        existing = self.get_persistent_token()
        if existing:
            self._pairing_token = existing
            return existing
        self._pairing_token = uuid.uuid4().hex
        self.save_persistent_token(self._pairing_token)
        return self._pairing_token

    def save_persistent_token(self, token: str):
        os.makedirs(os.path.dirname(PAIRING_FILE), exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(PAIRING_FILE, flags, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(token)
        os.chmod(PAIRING_FILE, 0o600)

    def verify_token(self, token: str) -> bool:
        candidate = (token or "").strip()
        if not candidate:
            return False
        persisted = self.get_persistent_token()
        if persisted and persisted == candidate:
            return True
        if self._pairing_token and self._pairing_token == candidate:
            return True
        return False

    async def send_message(self, message: dict) -> bool:
        connection = self.connection
        if not connection:
            return False
        try:
            await connection.send_json(message)
            return True
        except Exception:
            if self.connection is connection:
                self._mark_disconnected()
            return False

    async def disconnect(self, ws: WebSocket | None = None):
        connection = self.connection if ws is None else ws
        if connection is None:
            if ws is None:
                self._mark_disconnected()
            return
        try:
            await connection.close()
        except Exception:
            pass
        if self.connection is connection:
            self._mark_disconnected()


extension_manager = ExtensionManager()


def _reported_reload_generation(payload: dict) -> str | None:
    reported = payload.get("reload_generation")
    if reported is None:
        return None
    token = str(reported).strip()
    return token or None


def _reported_build(payload: dict) -> str | None:
    reported = payload.get("build")
    if reported is None:
        return None
    text = str(reported).strip()
    return text or None


def _reported_version(payload: dict) -> str | None:
    version = payload.get("version")
    if version is None:
        return None
    text = str(version).strip()
    return text or None


async def request_extension_reload(generation: str) -> bool:
    return await extension_manager.send_message(ProtocolMessage(
        type="extension.reload",
        payload={"generation": generation},
    ).model_dump(mode="json"))


async def wait_for_extension_connection(
    timeout_sec: float = 20.0,
    *,
    poll_interval_sec: float = 0.25,
) -> bool:
    """Wait until the bridge pairs after Connect Chrome opens everyday Chrome.

    MV3 workers often need a moment (and sometimes one reload) before the
    WebSocket is live. Keep nudging a pending reload while we wait so a single
    Connect click can finish the handshake without quitting Chrome.
    """
    deadline = time.monotonic() + max(0.0, timeout_sec)
    last_reload_at = 0.0
    while True:
        if extension_manager.connected:
            return True
        now = time.monotonic()
        if now >= deadline:
            return extension_manager.connected
        if now - last_reload_at >= 2.0:
            token = pending_extension_reload_token()
            if not token:
                token = extension_reload_token_if_needed(
                    extension_manager.version,
                    extension_manager.reload_generation,
                    extension_manager.build,
                )
            if token and extension_manager.connection is not None:
                await request_extension_reload(token)
            last_reload_at = now
        await asyncio.sleep(poll_interval_sec)


async def handshake_extension(
    ws: WebSocket,
    reported_generation: str | None,
    reported_version: str | None = None,
    reported_build: str | None = None,
) -> bool:
    try:
        install_bundled_extension()
    except ChromeBridgeError:
        pass
    token = extension_reload_token_if_needed(reported_version, reported_generation, reported_build)
    if token:
        # One worker reload when Chrome is not yet on this Studio copy. A
        # second pass with the same generation is accepted so Vendoo tabs
        # are not reloaded in a loop.
        await ws.send_json(ProtocolMessage(
            type="extension.reload",
            payload={"generation": token},
        ).model_dump(mode="json"))
        return False
    clear_extension_reload_pending()
    await ws.send_json(ProtocolMessage(
        type="connection.accepted",
        payload={"paired": True},
    ).model_dump(mode="json"))
    return True


def schedule_advance_job_queue() -> None:
    """Kick the FIFO dispatcher from sync or fire-and-forget contexts."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(dispatch_queued_jobs())


_saved_item_syncs: set[asyncio.Task] = set()


def _schedule_saved_item_sync(conv_id: str) -> None:
    """Pull a draft the seller just saved in Vendoo.

    Runs beside the socket loop, which has to keep reading for the extension
    to answer the get_item this sync sends.
    """
    from vendoo_studio.services.vendoo_watch import sync_conversation

    async def run() -> None:
        try:
            with SessionLocal() as db:
                await sync_conversation(db, conv_id)
        except Exception:
            log.exception("Vendoo save sync failed for %s", conv_id)

    from vendoo_studio.services import activity

    task = activity.track_task(conv_id, "Syncing from Vendoo…", asyncio.create_task(run()))
    _saved_item_syncs.add(task)
    task.add_done_callback(_saved_item_syncs.discard)


async def dispatch_queued_jobs():
    from vendoo_studio.services.category_tree import syncing
    if syncing():
        return
    db = SessionLocal()
    try:
        from vendoo_studio.repositories.queries import JobRepo
        from vendoo_studio.services.schema_probe import is_schema_probe_job, listing_for_extension
        from vendoo_studio.models.job import is_vendoo_api_step
        repo = JobRepo(db)
        # One Chrome fill at a time; later approvals wait in queued / awaiting_extension.
        if repo.get_running():
            return
        jobs = [job for job in repo.get_dispatchable() if not is_vendoo_api_step(job.current_step)]
        if not jobs:
            return
        if not extension_manager.connected:
            for job in jobs:
                if job.status != "awaiting_extension":
                    repo.update_status(job.id, "awaiting_extension", "awaiting_extension")
            return
        job = jobs[0]
        photos_list = _build_photo_list(job.conversation_id, db)
        from vendoo_studio.repositories.queries import ConversationRepo
        from vendoo_studio.services.marketplaces import selected_fillable_platforms
        from vendoo_studio.services.chrome_bridge import listing_url_for_job
        from vendoo_studio.services.vendoo_import import vendoo_binding
        conv = ConversationRepo(db).get(job.conversation_id)
        binding = vendoo_binding(conv.notes if conv else None)
        item_id = durable_vendoo_item_id(job.vendoo_item_id or binding.get("vendooItemId"))
        item_url = listing_url_for_job(item_id, job.vendoo_url or binding.get("vendooUrl"))
        reuse_existing = bool(item_id or item_url)
        schema_probe = is_schema_probe_job(job)
        snapshot = job.listing_snapshot if isinstance(job.listing_snapshot, dict) else {}
        stamped_platforms = snapshot.get("platforms") if isinstance(snapshot.get("platforms"), list) else []
        platforms = selected_fillable_platforms(stamped_platforms)
        registry_selectors = _build_registry_selectors(snapshot, db, platforms)
        registry_options = _build_registry_options(
            db, platforms, str(snapshot.get("category_path") or "").strip() or None
        )
        resume_from = None
        retried = repo.latest_event(job.id, "retried")
        if retried and isinstance(retried.payload, dict):
            candidate = str(retried.payload.get("resume_from") or "").strip()
            resume_from = candidate or None
        options = {
            "platforms": platforms,
            "saveDrafts": True,
            "publish": False,
            "reuseExistingItem": reuse_existing,
            "skipPhotos": bool(schema_probe),
            # Imported drafts keep matching values; fill skips unchanged fields.
            "clearBeforeFill": False,
            "vendoo_item_id": item_id,
            "vendoo_url": item_url,
        }
        category_path = str(snapshot.get("category_path") or "").strip()
        if (
            not schema_probe
            and platforms
            and category_path
        ):
            from vendoo_studio.services.category_catalog import schema_covers_platforms
            if schema_covers_platforms(db, category_path, platforms):
                # Cached schema already learned for this category — skip the live
                # marketplace tour. Fill still sets categories when needed.
                options["skipDiscoverSchema"] = True
        if resume_from:
            options["resumeFrom"] = resume_from
        if schema_probe:
            options["mode"] = "schema_probe"
            options["skipPhotos"] = True
            options.pop("skipDiscoverSchema", None)
        sent = await extension_manager.send_message(ProtocolMessage(
            type="job.start",
            job_id=job.id,
            message_id=uuid.uuid4().hex[:12],
            payload={
                "job_id": job.id,
                "listing": listing_for_extension(job.listing_snapshot),
                "photos": [] if schema_probe else photos_list,
                "vendoo_item_id": item_id,
                "vendoo_url": item_url,
                "options": options,
                "registry_selectors": registry_selectors,
                "registry_options": registry_options,
            },
        ).model_dump(mode="json"))
        if sent:
            repo.update_status(job.id, "dispatched")
        else:
            repo.update_status(job.id, "awaiting_extension", "awaiting_extension")
    finally:
        db.close()


async def dispatch_fill_fields(
    job,
    fields: list[dict],
    *,
    verify: bool = True,
    platforms: list[str] | None = None,
    reload: bool = False,
    read_item: bool = False,
) -> bool:
    if not extension_manager.connected:
        return False
    from sqlalchemy.orm import object_session
    from vendoo_studio.repositories.queries import ConversationRepo
    db = object_session(job)
    photo_count = len(ConversationRepo(db).get_photos(job.conversation_id)) if db is not None else 0
    snapshot_platforms = (job.listing_snapshot or {}).get("platforms") or []
    return await extension_manager.send_message(ProtocolMessage(
        type="job.fill_fields",
        job_id=job.id,
        message_id=uuid.uuid4().hex[:12],
        payload={
            "job_id": job.id,
            "vendoo_item_id": job.vendoo_item_id,
            "vendoo_url": job.vendoo_url,
            "fields": fields,
            "listing": {key: value for key, value in (job.listing_snapshot or {}).items() if not key.startswith("_")},
            "platforms": list(platforms) if platforms is not None else list(snapshot_platforms),
            "expected_photo_count": photo_count,
            # Manual Apply skips full draft readback; completion repair keeps verify=True.
            "verify": bool(verify),
            "reload": bool(reload),
            # Read the saved item over the API before closing the tab (refreshes the draft cache).
            "read_item": bool(read_item),
        },
    ).model_dump(mode="json"))


async def dispatch_vendoo_get(job, request_id: str, *, api_only: bool = False, resolve_photos: bool = False) -> bool:
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
            # Skip the per-marketplace form tour when the item API answers.
            "api_only": bool(api_only),
            # Blob: preview photos only exist inside the Vendoo tab; upload them
            # straight from there when the caller is about to import this draft.
            "resolve_photos": bool(resolve_photos),
            "conversation_id": job.conversation_id if resolve_photos else None,
        },
    ).model_dump(mode="json"))


async def dispatch_search_categories(job, request_id: str, query: str) -> bool:
    if not extension_manager.connected:
        return False
    from vendoo_studio.services.chrome_bridge import listing_url_for_job
    from vendoo_studio.services.marketplaces import selected_fillable_platforms

    snapshot = job.listing_snapshot if isinstance(job.listing_snapshot, dict) else {}
    stamped = snapshot.get("platforms") if isinstance(snapshot.get("platforms"), list) else []
    item_id = durable_vendoo_item_id(job.vendoo_item_id)
    item_url = listing_url_for_job(item_id, job.vendoo_url)
    return await extension_manager.send_message(ProtocolMessage(
        type="job.search_categories",
        job_id=job.id,
        message_id=request_id,
        payload={
            "job_id": job.id,
            "request_id": request_id,
            "query": query,
            "platforms": selected_fillable_platforms(stamped),
            "vendoo_item_id": item_id,
            "vendoo_url": item_url,
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


async def dispatch_show_vendoo() -> bool:
    if not extension_manager.connected:
        return False
    return await extension_manager.send_message(ProtocolMessage(
        type="job.open_listing",
        message_id=uuid.uuid4().hex[:12],
        payload={"vendoo_url": "https://web.vendoo.co/app"},
    ).model_dump(mode="json"))


def _build_photo_list(conv_id: str, db) -> list[dict]:
    from vendoo_studio.repositories.queries import ConversationRepo
    repo = ConversationRepo(db)
    photos = repo.get_photos(conv_id)
    return [{"id": p.id, "name": p.original_filename, "stored_filename": p.stored_filename} for p in photos]


def _learn_schema_options(db, job, schema: dict) -> dict:
    """Persist live dropdown options captured by the schema probe.

    The probe walks every marketplace panel in one step, so options are filed
    per platform here rather than through the diagnostics path, which derives a
    single marketplace from the step name.
    """
    from vendoo_studio.repositories.queries import RegistryRepo

    snapshot = job.listing_snapshot if isinstance(job.listing_snapshot, dict) else {}
    category_path = str(snapshot.get("category_path") or "").strip() or None

    repo = RegistryRepo(db)
    learned: dict[str, int] = {}
    for platform, section in (schema or {}).items():
        fields = (section or {}).get("fields") or []
        with_options = [f for f in fields if isinstance(f, dict) and f.get("options")]
        if not with_options:
            continue
        try:
            repo.upsert_schema_fields(str(platform), category_path, with_options)
        except Exception:
            log.exception("registry upsert failed for %s", platform)
            db.rollback()
            continue
        learned[str(platform)] = len(with_options)
    if learned:
        log.info("schema probe learned options for %s (category=%s)", learned, category_path)
    return learned


def _build_registry_options(db, platforms: list[str], category_path: str | None) -> dict:
    """Known dropdown options per marketplace so the extension can repair stale values."""
    from vendoo_studio.repositories.queries import RegistryRepo

    repo = RegistryRepo(db)
    result = {}
    for marketplace in [*platforms, "general"]:
        options = repo.options_by_label(marketplace, category_path)
        if options:
            result[marketplace] = options
    return result


def _build_registry_selectors(listing: dict, db, platforms: list[str]) -> dict:
    from vendoo_studio.repositories.queries import RegistryRepo
    repo = RegistryRepo(db)
    category_path = listing.get("category_path", "")

    result = {}
    for marketplace in platforms:
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
    from vendoo_studio.services.schema_probe import is_schema_probe_job
    job = JobRepo(db).get(job_id)
    if not job:
        return
    # Schema probes must not flip draft listings to listing/completed/failed.
    if is_schema_probe_job(job):
        return
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
        **extension_build_status(
            extension_manager.version,
            extension_manager.reload_generation,
            extension_manager.build,
        ),
    }


@router.post("/api/extension/reload")
async def reload_extension():
    try:
        result = relaunch_studio_chrome(visible=True)
    except ChromeBridgeError as exc:
        raise HTTPException(400, str(exc)) from exc
    result["sent"] = True
    return result


@router.websocket("/api/extension/ws")
async def extension_websocket(ws: WebSocket):
    if not _websocket_allowed(ws):
        await ws.close(code=1008)
        return

    await ws.accept()
    db = SessionLocal()
    try:
        while True:
            raw = await ws.receive_text()
            message = json.loads(raw)

            msg_type = message.get("type", "")

            if msg_type == "extension.ready":
                payload = message.get("payload", {}) or {}
                token = payload.get("token", "")
                if not extension_manager.verify_token(token):
                    await ws.send_json({"type": "error", "message": "Invalid pairing token"})
                    continue
                old = extension_manager.connection
                extension_manager.connection = ws
                extension_manager.version = _reported_version(payload)
                extension_manager.build = _reported_build(payload)
                extension_manager.reload_generation = _reported_reload_generation(payload)
                if old is not None and old is not ws:
                    try:
                        await old.close()
                    except Exception:
                        pass
                accepted = await handshake_extension(
                    ws,
                    _reported_reload_generation(payload),
                    _reported_version(payload),
                    _reported_build(payload),
                )
                if accepted:
                    extension_manager.paired = True
                    from vendoo_studio.repositories.queries import JobRepo
                    JobRepo(db).requeue_interrupted()
                    await dispatch_queued_jobs()
                    # Warm label names in the background so Item Details can rename
                    # opaque chips without blocking the handshake.
                    asyncio.create_task(_warm_label_catalog())
                continue

            if extension_manager.connection is not ws or not extension_manager.paired:
                await ws.send_json({"type": "error", "message": "Not paired"})
                continue

            job_id = message.get("job_id")
            if (
                job_id
                and str(msg_type).startswith("job.")
                # Preview frames also stream while the seller browses a finished draft.
                and msg_type not in {"job.vendoo_item", "job.categories", "job.preview_frame"}
            ):
                from vendoo_studio.models.job import is_terminal_job_status
                from vendoo_studio.repositories.queries import JobRepo
                current_job = JobRepo(db).get(job_id)
                if current_job and is_terminal_job_status(current_job.status):
                    JobRepo(db).add_event(job_id, "ignored_late_result", None, {"type": msg_type})
                    continue

            if msg_type == "browser.result":
                payload = message.get("payload") or {}
                extension_manager.resolve_wait(str(payload.get("request_id") or ""), payload)
                continue

            if msg_type == "catalog.children":
                payload = message.get("payload") or {}
                extension_manager.resolve_wait(str(payload.get("request_id") or ""), payload)
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
                    vid = durable_vendoo_item_id(payload.get("vendoo_item_id"))
                    vurl = payload.get("vendoo_url")
                    if isinstance(vurl, str) and "/item/new" in vurl:
                        vurl = None
                    job = repo.get(job_id)
                    if step == "filling_fields":
                        job = repo.get(job_id)
                        if job and payload.get("fill_log"):
                            FillLogService(db).apply_field_results(job, payload.get("fill_log"))
                        if job and isinstance(payload.get("item"), dict):
                            repo.save_vendoo_draft(
                                job_id,
                                item=payload["item"],
                                item_id=vid or job.vendoo_item_id,
                                url=vurl or job.vendoo_url,
                                source="api_readback",
                                step="fields_applied",
                            )
                        verification = payload.get("verification")
                        if isinstance(verification, dict):
                            # Completion repair path — read back every marketplace and continue.
                            repo.update_status(job_id, "dispatched", "verifying_draft", vendoo_item_id=vid, vendoo_url=vurl)
                            repo.add_event(job_id, "step_completed", step, payload)
                            job = repo.get(job_id)
                            if job:
                                from vendoo_studio.services.listing_completion import store_verification, schedule_completion
                                store_verification(db, job, verification)
                                schedule_completion(job_id)
                        else:
                            # Manual Apply — only the requested empty fields were typed.
                            repo.update_status(job_id, "completed", "fields_applied", vendoo_item_id=vid, vendoo_url=vurl)
                            repo.add_event(job_id, "step_completed", step, payload)
                            _set_conversation_status(db, job_id, "draft")
                            await dispatch_queued_jobs()
                    else:
                        repo.update_status(job_id, "dispatched", step, vendoo_item_id=vid, vendoo_url=vurl)
                        repo.add_event(job_id, "step_completed", step, payload)
                        job = repo.get(job_id)
                        if job and payload.get("fill_log"):
                            FillLogService(db).save_step(job, step, payload.get("fill_log"))
                        if step == "discovering_schema" and job and payload.get("schema"):
                            from vendoo_studio.services.category_catalog import remember_schema
                            remember_schema(db, str((job.listing_snapshot or {}).get("category_path") or ""), payload["schema"])
                            schema = payload.get("schema") or {}
                            learned = _learn_schema_options(db, job, schema)
                            repo.add_event(job_id, "schema_discovered", step, {
                                "platforms": list(schema.keys()),
                                "categories": payload.get("categories") or {},
                                "field_counts": {
                                    platform: len((section or {}).get("fields") or [])
                                    for platform, section in schema.items()
                                },
                                "option_counts": learned,
                            })
                        _set_conversation_status(db, job_id, "listing")

            elif msg_type == "job.step_failed":
                payload = message.get("payload", {})
                job_id = message.get("job_id")
                if job_id:
                    from vendoo_studio.repositories.queries import ConversationRepo, JobRepo
                    from vendoo_studio.services.fill_log import FillLogService
                    from vendoo_studio.services.schema_probe import is_schema_probe_job
                    repo = JobRepo(db)
                    err = payload.get("error", "Unknown error")
                    step = payload.get("step", "")
                    job = repo.get(job_id)
                    if step == "filling_fields":
                        restore = "failed"
                        repo.update_status(job_id, restore, step, error=err)
                        repo.add_event(job_id, "step_failed", step, payload)
                        job = repo.get(job_id)
                        if job and payload.get("fill_log"):
                            FillLogService(db).apply_field_results(job, payload.get("fill_log"))
                        _set_conversation_status(db, job_id, "draft")
                        await dispatch_queued_jobs()
                    else:
                        repo.update_status(job_id, "failed", step, error=err)
                        repo.add_event(job_id, "step_failed", step, payload)
                        job = repo.get(job_id)
                        if job and payload.get("fill_log"):
                            FillLogService(db).save_step(job, step, payload.get("fill_log"))
                        if is_schema_probe_job(job):
                            extension_manager.resolve_wait("schema:" + job_id, {"ok": False, "error": err})
                            ConversationRepo(db).add_message(
                                job.conversation_id,
                                "system",
                                f"Could not discover Vendoo fields at step “{step or 'unknown'}” "
                                f"(job {job_id}): {err}",
                                provider="system",
                                model="",
                            )
                        else:
                            _set_conversation_status(db, job_id, "failed")
                        await dispatch_queued_jobs()

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

            elif msg_type == "vendoo.item_saved":
                payload = message.get("payload") or {}
                item_id = str(payload.get("item_id") or "").strip()
                if item_id:
                    from vendoo_studio.repositories.queries import ConversationRepo

                    conv = ConversationRepo(db).find_by_vendoo_item_id(item_id)
                    if conv:
                        _schedule_saved_item_sync(conv.id)

            elif msg_type == "job.vendoo_api_result":
                payload = message.get("payload") or {}
                request_id = payload.get("request_id") or message.get("message_id")
                if request_id:
                    extension_manager.resolve_wait(str(request_id), payload)
                job_id = message.get("job_id")
                if job_id:
                    from vendoo_studio.repositories.queries import JobRepo
                    JobRepo(db).add_event(job_id, "vendoo_api", None, {
                        "ok": bool(payload.get("ok")),
                        "ops": [r.get("op") for r in (payload.get("results") or []) if isinstance(r, dict)],
                        "error": payload.get("error"),
                    })

            elif msg_type == "job.categories":
                payload = message.get("payload") or {}
                request_id = payload.get("request_id") or message.get("message_id")
                if request_id:
                    extension_manager.resolve_wait(str(request_id), payload)
                job_id = message.get("job_id")
                if job_id:
                    from vendoo_studio.repositories.queries import JobRepo
                    repo = JobRepo(db)
                    repo.add_event(job_id, "search_categories", None, {
                        "ok": bool(payload.get("ok")),
                        "query": payload.get("query"),
                        "path": payload.get("path"),
                        "error": payload.get("error"),
                    })

            elif msg_type == "job.completed":
                job_id = message.get("job_id")
                payload = message.get("payload") or {}
                if job_id:
                    from vendoo_studio.repositories.queries import ConversationRepo, JobRepo
                    from vendoo_studio.services.schema_probe import bind_probe_draft, is_schema_probe_job
                    repo = JobRepo(db)
                    vurl = payload.get("vendoo_url", "")
                    if isinstance(vurl, str) and "/item/new" in vurl:
                        vurl = ""
                    item_id = durable_vendoo_item_id(payload.get("vendoo_item_id"))
                    job = repo.get(job_id)
                    if job and is_schema_probe_job(job):
                        repo.update_status(
                            job_id,
                            "completed",
                            current_step="schema_probe_done",
                            vendoo_url=vurl or job.vendoo_url,
                            vendoo_item_id=item_id or job.vendoo_item_id,
                        )
                        bind_probe_draft(db, job)
                        repo.add_event(job_id, "completed", "schema_probe_done", {
                            "mode": "schema_probe",
                            "vendoo_url": vurl or job.vendoo_url,
                        })
                        path = str((job.listing_snapshot or {}).get("category_path") or "").strip()
                        ConversationRepo(db).add_message(
                            job.conversation_id,
                            "system",
                            (
                                f"Marketplace fields discovered for {path}."
                                if path else
                                "Marketplace fields discovered from Vendoo."
                            ),
                            provider="system",
                            model="",
                        )
                        extension_manager.resolve_wait("schema:" + job_id, {"ok": True})
                        await dispatch_queued_jobs()
                    elif job:
                        from vendoo_studio.services.listing_completion import store_verification, schedule_completion
                        repo.update_status(job_id, "dispatched", "verifying_draft",
                                           vendoo_url=vurl or job.vendoo_url,
                                           vendoo_item_id=item_id or job.vendoo_item_id)
                        store_verification(db, job, payload.get("verification") or {})
                        schedule_completion(job_id)

            elif msg_type == "job.cancelled":
                job_id = message.get("job_id")
                if job_id:
                    from vendoo_studio.repositories.queries import JobRepo
                    from vendoo_studio.services.schema_probe import is_schema_probe_job
                    repo = JobRepo(db)
                    job = repo.get(job_id)
                    repo.update_status(job_id, "cancelled")
                    repo.add_event(job_id, "cancelled")
                    if not is_schema_probe_job(job):
                        _set_conversation_status(db, job_id, "draft")
                    await dispatch_queued_jobs()

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
            extension_manager._mark_disconnected()
        db.close()
