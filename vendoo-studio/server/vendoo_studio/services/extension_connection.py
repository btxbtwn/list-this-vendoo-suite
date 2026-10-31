from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Literal

from fastapi import HTTPException, WebSocket, WebSocketDisconnect

from vendoo_studio.config import PAIRING_FILE
from vendoo_studio.models.protocol import ProtocolMessage
from vendoo_studio.database import SessionLocal
from vendoo_studio.services.chrome_bridge import (
    ChromeBridgeError,
    clear_extension_reload_pending,
    extension_build_status,
    extension_in_lockstep,
    extension_reload_token_if_needed,
    install_bundled_extension,
    pending_extension_reload_token,
)

log = logging.getLogger("vendoo_studio.extension")

VENDOO_GET_TIMEOUT_SEC = 120
# A message is a few KB. A send that has not gone out in this long is waiting on
# an extension that stopped reading, and would otherwise wait forever.
SEND_TIMEOUT_SEC = 5.0
# Showing a tab is quick; past this Studio opens the listing in Chrome itself.
OPEN_LISTING_TIMEOUT_SEC = 8.0
# A worker that pairs again this soon after the last pairing is flapping rather
# than reconnecting: resuming interrupted sends and reconciling direct listings
# on every one of those ticks re-queues work and keeps Chrome busy in a loop.
RECONNECT_SETTLE_SEC = 5.0
# A socket that drops this fast never held a conversation, so say so in the log.
FLAP_WARN_SEC = 10.0
ROUTE_ITEM_IDS = frozenset({"new", "edit", "create"})
# Two copies of the bridge (the app's folder plus an older Anteroom data folder,
# or a checkout loaded by hand) both pair. Each pairing used to close the
# other's socket, so they closed each other every half second and the replies in
# flight went with them: a form read failed and a listing check never finished.
DUPLICATE_BRIDGE = (
    "Another copy of the Anteroom Bridge is loaded in Chrome. Remove it in chrome://extensions, "
    "keep the copy Settings → Connections names, then reload that one."
)
# How long a refusal keeps saying so, so a seller who opens Settings sees it.
DUPLICATE_REPORT_SEC = 300.0


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
    from vendoo_studio.services.local_requests import origin_allowed

    value = (origin or "").strip()
    if not value:
        return False
    return origin_allowed(value, extension=True)


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
        # The server's event loop, for the sourcing thread to reach Chrome through.
        self.loop: asyncio.AbstractEventLoop | None = None
        self._pairing_token: str | None = None
        self._waits: dict[str, asyncio.Future] = {}
        self._wait_jobs: dict[str, str] = {}
        # Monotonic time of the last accepted pairing, kept across disconnects so
        # a reconnect loop is visible as one.
        self._last_handshake_at: float | None = None
        self._duplicate_refused_at: float | None = None

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

    def is_waiting(self, request_id: str) -> bool:
        fut = self._waits.get(request_id)
        return bool(fut and not fut.done())

    def cancel_wait(self, request_id: str) -> None:
        self._wait_jobs.pop(request_id, None)
        fut = self._waits.pop(request_id, None)
        if fut and not fut.done():
            fut.cancel()

    def cancel_waits_for_job(self, job_id: str) -> None:
        for request_id, wait_job_id in list(self._wait_jobs.items()):
            if wait_job_id == job_id:
                self.cancel_wait(request_id)

    def note_handshake(self, now: float | None = None) -> bool:
        """Record an accepted pairing. True when it is not part of a reconnect loop.

        A worker that pairs, drops and pairs again every second looks healthy
        from the outside while it re-runs the work a reconnect implies. Those
        side effects only run for a pairing that stands on its own.
        """
        moment = time.monotonic() if now is None else now
        previous = self._last_handshake_at
        self._last_handshake_at = moment
        return previous is None or (moment - previous) >= RECONNECT_SETTLE_SEC

    def _mark_disconnected(self) -> None:
        self.connection = None
        self.paired = False
        self.version = None
        self.build = None
        self.reload_generation = None

    def claims_connection(self, version: str | None, build: str | None) -> bool:
        """Whether a connecting copy may take the socket from the paired one.

        A connected copy is only replaced by one that runs this app's extension
        while the paired copy does not. Anything else is a second copy asking
        while the first is healthy, and taking it would drop every request in
        flight and hand the socket back a moment later, forever.
        """
        if self.connection is None or not self.paired:
            return True
        if extension_in_lockstep(build, version) and not extension_in_lockstep(self.build, self.version):
            return True
        self._duplicate_refused_at = time.monotonic()
        return False

    @property
    def duplicate_bridge(self) -> bool:
        """True when a second copy asked to connect in the last few minutes."""
        if self._duplicate_refused_at is None:
            return False
        if time.monotonic() - self._duplicate_refused_at > DUPLICATE_REPORT_SEC:
            self._duplicate_refused_at = None
            return False
        return True

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
            await asyncio.wait_for(connection.send_json(message), SEND_TIMEOUT_SEC)
            return True
        except Exception:
            # Studio closing the socket on purpose is the other half of a
            # reconnect loop; name it, or a flapping bridge looks like Chrome's
            # fault alone.
            log.warning(
                "Extension send failed (%s); closing the socket so it reconnects",
                message.get("type"),
                exc_info=True,
            )
            if self.connection is connection:
                self._mark_disconnected()
                # Closing makes the extension reconnect on a fresh socket.
                try:
                    await asyncio.wait_for(connection.close(), 1.0)
                except Exception:
                    pass
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
_reconnect_tasks: set[asyncio.Task] = set()


def _run_reconnect_work(db) -> bool:
    """Resume what a reconnect implies, once the pairing is not itself a flap.

    A worker that pairs, drops and pairs again every half second looks paired
    each time. Resuming interrupted sends and reconciling direct listings on
    every one of those ticks re-queues work and keeps asking Chrome for a
    listing check it cannot answer, until the check times out. So the work
    waits for a pairing that stands on its own.
    """
    if not extension_manager.note_handshake():
        log.info("Extension paired again within %ss; holding reconnect work", RECONNECT_SETTLE_SEC)
        return False

    from vendoo_studio.repositories.queries import JobRepo

    _resume_interrupted_sends(JobRepo(db), JobRepo(db).requeue_interrupted())

    from vendoo_studio.services.native_marketplaces import reconcile_then_dispatch

    # Read unconfirmed direct listings before a queued Send takes Chrome. Off
    # this loop: the checks wait on replies it reads.
    _reconnect_tasks.add(task := asyncio.create_task(reconcile_then_dispatch()))
    task.add_done_callback(_reconnect_tasks.discard)
    # Warm label names in the background so Item Details can rename opaque chips
    # without blocking the handshake.
    asyncio.create_task(_warm_label_catalog())
    return True


async def _reconnect_work_after_settle(ws: WebSocket) -> None:
    """Run the reconnect work for a pairing that was too soon, if it survives."""
    await asyncio.sleep(RECONNECT_SETTLE_SEC)
    if extension_manager.connection is not ws:
        # It flapped again; whichever pairing outlasts the window decides.
        return
    with SessionLocal() as db:
        _run_reconnect_work(db)


def _after_pairing(db, ws: WebSocket) -> None:
    """Do the reconnect work now, or once a flapping pairing has settled."""
    if _run_reconnect_work(db):
        return
    _reconnect_tasks.add(task := asyncio.create_task(_reconnect_work_after_settle(ws)))
    task.add_done_callback(_reconnect_tasks.discard)


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


_dispatch_locks: dict[asyncio.AbstractEventLoop, asyncio.Lock] = {}


def _dispatch_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _dispatch_locks.get(loop)
    if lock is None:
        _dispatch_locks.clear()
        lock = _dispatch_locks[loop] = asyncio.Lock()
    return lock


def _set_job_status(job_id: str, status: str, step: str | None = None) -> None:
    from vendoo_studio.repositories.queries import JobRepo
    with SessionLocal() as db:
        if step is None:
            JobRepo(db).update_status(job_id, status)
        else:
            JobRepo(db).update_status(job_id, status, step)


def _next_dispatch() -> tuple[str, str, dict | None] | None:
    """Pick the next queued job and claim or build its start. Runs in a thread.

    Returns ``("api", job_id, None)`` for a Vendoo API send already marked
    dispatched, ``("start", job_id, message)`` for an extension fill to send,
    or None when nothing should start.
    """
    from vendoo_studio.repositories.queries import JobRepo
    from vendoo_studio.services.schema_probe import is_schema_probe_job, listing_for_extension
    from vendoo_studio.models.job import is_vendoo_api_step
    with SessionLocal() as db:
        repo = JobRepo(db)
        # One Chrome fill at a time; later approvals wait in queued / awaiting_extension.
        if repo.get_running():
            return None
        jobs = repo.get_dispatchable()
        if not jobs:
            return None
        job = jobs[0]
        if is_vendoo_api_step(job.current_step):
            if not extension_manager.connected:
                return None
            from vendoo_studio.services.vendoo_send import CREATE_STEP, SAVE_STEP
            from vendoo_studio.services.api_job_lock import claim_api_job, start_gate

            with start_gate():
                if repo.get_running():
                    return None
                repo.update_status(job.id, "dispatched", SAVE_STEP if job.vendoo_item_id else CREATE_STEP)
                claim_api_job(job.id)
            return ("api", job.id, None)
        if not extension_manager.connected:
            for job in jobs:
                if job.status != "awaiting_extension":
                    repo.update_status(job.id, "awaiting_extension", "awaiting_extension")
            return None
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
        return ("start", job.id, ProtocolMessage(
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


def _resume_interrupted_sends(repo, jobs) -> None:
    """Start sends cut off by a Chrome reconnect again, once their worker stops.

    A worker still running here waits on replies the old connection will never
    deliver, so its waits are cancelled; it ends now and its own exit queues the
    send again. A send with no worker (Studio restarted) is queued straight away.
    """
    from vendoo_studio.models.job import RECONNECTED_SEND
    from vendoo_studio.services.api_job_lock import api_job_is_live

    for job in jobs:
        if job.status != "failed" or job.last_error != RECONNECTED_SEND:
            continue
        if api_job_is_live(job.id):
            extension_manager.cancel_waits_for_job(job.id)
        else:
            repo.requeue_interrupted_send(job.id)


async def dispatch_queued_jobs():
    """Start the next queued job, if Chrome is free.

    The database work runs in a thread so a busy SQLite lock cannot stall the
    event loop, and one dispatch runs at a time so two callers cannot both see
    the slot free and start the same job.
    """
    from vendoo_studio.services.category_tree import syncing
    from vendoo_studio.services.user_settings import vendoo_enabled

    if not vendoo_enabled() or syncing():
        return
    async with _dispatch_lock():
        picked = await asyncio.to_thread(_next_dispatch)
        if picked is None:
            return
        kind, job_id, message = picked
        if kind == "api":
            from vendoo_studio.services.send_queue import run_send
            from vendoo_studio.services.streaming import spawn
            spawn(run_send(job_id))
            return
        sent = await extension_manager.send_message(message)
        if sent:
            await asyncio.to_thread(_set_job_status, job_id, "dispatched")
        else:
            await asyncio.to_thread(_set_job_status, job_id, "awaiting_extension", "awaiting_extension")


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
    """True once the extension says the listing tab is showing.

    Handing the message over is not enough: an extension that is paired but
    stuck takes it and opens nothing, which reads as a button that never works.
    """
    if not extension_manager.connected:
        return False
    request_id = uuid.uuid4().hex
    waiter = extension_manager.register_wait(request_id)
    sent = await extension_manager.send_message(ProtocolMessage(
        type="job.open_listing",
        job_id=job.id,
        message_id=request_id,
        payload={
            "job_id": job.id,
            "vendoo_item_id": job.vendoo_item_id,
            "vendoo_url": job.vendoo_url,
            "request_id": request_id,
        },
    ).model_dump(mode="json"))
    if not sent:
        extension_manager.cancel_wait(request_id)
        return False
    try:
        result = await asyncio.wait_for(waiter, OPEN_LISTING_TIMEOUT_SEC)
    except (TimeoutError, asyncio.CancelledError):
        extension_manager.cancel_wait(request_id)
        log.info("extension did not open listing for job %s; opening Chrome directly", job.id)
        return False
    return bool(isinstance(result, dict) and result.get("ok"))


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
                        "value": value if value is not None else "",
                    }
        result[marketplace] = fields

    general_fields = {}
    for field_label in ("title", "description", "brand", "tags", "sku", "condition"):
        selectors = repo.get_best_selectors("general", field_label, category_path)
        if selectors:
            general_fields[field_label] = {
                "selectors": selectors,
                "value": listing.get(field_label, ""),
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


def get_pairing_token():
    token = extension_manager.generate_pairing_token()
    return {"token": token}


def extension_status():
    return {
        "connected": extension_manager.connected,
        "paired": extension_manager.paired,
        "duplicate_bridge": extension_manager.duplicate_bridge,
        **extension_build_status(
            extension_manager.version,
            extension_manager.reload_generation,
            extension_manager.build,
        ),
    }


async def reload_extension():
    try:
        from vendoo_studio.services.chrome_bridge import sync_bundled_extension

        await asyncio.to_thread(sync_bundled_extension)
    except ChromeBridgeError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not extension_manager.connected:
        raise HTTPException(409, "Connect Chrome before reloading the bridge.")
    token = extension_reload_token_if_needed(extension_manager.version, extension_manager.reload_generation, extension_manager.build)
    return {"ok": True, "sent": await request_extension_reload(token) if token else False}


_SESSION_MARKETS = ("depop", "poshmark", "mercari", "sellwild", "vinted", "facebook")
_SESSION_STATES = {"signed_in", "expired", "signed_out", "unknown"}


def _public_session(raw: object) -> dict:
    """Sign-in summary only. Cookie values, tokens, and extra fields are dropped."""
    data = raw if isinstance(raw, dict) else {}
    state = data.get("state") if data.get("state") in _SESSION_STATES else "unknown"
    expires = data.get("expires_at")
    expires_at = int(expires) if isinstance(expires, (int, float)) and not isinstance(expires, bool) else None
    label = data.get("label")
    label = label.strip() if isinstance(label, str) else ""
    if not label or len(label) > 80:
        label = None
    if state == "signed_out":
        expires_at = None
        label = None
    return {
        "state": state,
        "expires_at": expires_at,
        "label": label,
        "expiring": bool(data.get("expiring")) and state == "signed_in",
    }


def _public_connect(raw: object) -> dict:
    data = raw if isinstance(raw, dict) else {}
    if data.get("ok") is not True:
        error = data.get("error")
        text = error.strip() if isinstance(error, str) else ""
        if not text or len(text) > 200:
            text = "Finish signing in in Chrome, then try again."
        return {"ok": False, "error": text}
    session = _public_session(data)
    return {"ok": True, "signed_in": session["state"] == "signed_in", **session}


async def marketplace_sessions():
    from types import SimpleNamespace

    from vendoo_studio.services import browser_bridge

    try:
        raw = await browser_bridge.request(SimpleNamespace(id=None), "marketplace.sessions", {}, timeout=20)
    except browser_bridge.BrowserBridgeError as exc:
        status = 409 if "Connect Chrome" in str(exc) else 502
        raise HTTPException(status, "Connect Chrome, then check marketplace sign-in.") from exc
    sessions = raw.get("sessions") if isinstance(raw, dict) else None
    if not isinstance(sessions, dict):
        raise HTTPException(502, "Chrome did not report marketplace sign-in.")
    return {"sessions": {name: _public_session(sessions.get(name)) for name in _SESSION_MARKETS}}


async def connect_marketplace(marketplace: str):
    from types import SimpleNamespace

    from vendoo_studio.services import browser_bridge

    if marketplace not in set(_SESSION_MARKETS):
        raise HTTPException(404, "Unknown marketplace.")
    try:
        raw = await browser_bridge.request(SimpleNamespace(id=None), "marketplace.connect", {"marketplace": marketplace}, timeout=40)
    except browser_bridge.BrowserBridgeError as exc:
        raise HTTPException(502, "Finish signing in in Chrome, then reconnect.") from exc
    return _public_connect(raw)


async def record_marketplace_requests(marketplace: str, goal: Literal["draft", "offers"] = "draft"):
    """Start recording the shape of a marketplace's own requests while the seller acts by hand.

    ``draft`` records a draft save; ``offers`` records the likers list and an offer
    sent to likers, reads included. Opens one tab for the seller; the result, request
    shapes only (operation names, GraphQL query text, paths, header names, value
    types), is saved when the tab closes and read with GET.
    """
    from vendoo_studio.services import marketplace_recording

    if marketplace not in marketplace_recording.RECORDABLE[goal]:
        raise HTTPException(404, "Recording is not set up for this marketplace.")
    if not marketplace_recording.start(marketplace, goal):
        raise HTTPException(409, "A recording is already running. Close its tab first.")
    return {"recording": True}


def recorded_marketplace_requests(marketplace: str, goal: Literal["draft", "offers"] = "draft"):
    from vendoo_studio.services import marketplace_recording

    if marketplace not in marketplace_recording.RECORDABLE[goal]:
        raise HTTPException(404, "Recording is not set up for this marketplace.")
    return marketplace_recording.status(marketplace, goal)


async def extension_websocket(ws: WebSocket):
    if not _websocket_allowed(ws):
        await ws.close(code=1008)
        return

    await ws.accept()
    opened_at = time.monotonic()
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
                version = _reported_version(payload)
                build = _reported_build(payload)
                if not extension_manager.claims_connection(version, build):
                    # Leave the paired copy alone and tell this one to stand down,
                    # rather than closing a working socket for a duplicate.
                    log.warning("Refused a second bridge copy (version %s, build %s)", version, build)
                    await ws.send_json({"type": "error", "message": DUPLICATE_BRIDGE, "duplicate_bridge": True})
                    continue
                old = extension_manager.connection
                extension_manager.connection = ws
                extension_manager.loop = asyncio.get_running_loop()
                extension_manager.version = version
                extension_manager.build = build
                extension_manager.reload_generation = _reported_reload_generation(payload)
                extension_manager._duplicate_refused_at = None
                if old is not None and old is not ws:
                    try:
                        await old.close()
                    except Exception:
                        pass
                accepted = await handshake_extension(
                    ws,
                    _reported_reload_generation(payload),
                    version,
                    build,
                )
                if accepted:
                    extension_manager.paired = True
                    _after_pairing(db, ws)
                continue

            if extension_manager.connection is not ws or not extension_manager.paired:
                await ws.send_json({"type": "error", "message": "Not paired"})
                continue

            if msg_type == "vendoo.api_log":
                from vendoo_studio.services.vendoo_api_log import ingest

                ingest(message.get("payload"))
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
                payload = message.get("payload") or {}
                request_id = str(payload.get("request_id") or message.get("message_id") or "")
                current_job = JobRepo(db).get(job_id)
                # A finished job is still read and updated (opening, reviewing or
                # updating a sent listing). A reply someone is waiting for is not
                # late; only drop the ones nobody asked for any more.
                if (
                    current_job
                    and is_terminal_job_status(current_job.status)
                    and not extension_manager.is_waiting(request_id)
                ):
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

            if msg_type == "market.sold_listings_result":
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

            elif msg_type == "job.vendoo_api_progress":
                from vendoo_studio.services.vendoo_send import record_photo_progress

                record_photo_progress(db, message.get("job_id"), message.get("payload", {}))

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
        lived = time.monotonic() - opened_at
        if lived < FLAP_WARN_SEC:
            # A worker that pairs and drops within seconds is flapping, and a
            # silent close is what let that go unnoticed.
            log.warning("Extension socket closed %.1fs after it paired", lived)
    except Exception:
        # Never swallow: a socket that dies mid-message has to leave a trace.
        log.warning("Extension socket failed after %.1fs", time.monotonic() - opened_at, exc_info=True)
    finally:
        if extension_manager.connection is ws:
            extension_manager._mark_disconnected()
        db.close()
