"""Interactive Vendoo browser: routes, WebSocket replies, and directed fills."""
from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services.extension_connection import ExtensionManager
from vendoo_studio.services.preview_hub import sanitize_frame


class FakeConnection:
    """Answers each browser request the way the extension would."""

    def __init__(self, manager: ExtensionManager, reply: dict):
        self.manager = manager
        self.reply = reply
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)
        request_id = (message.get("payload") or {}).get("request_id")
        if request_id:
            asyncio.get_running_loop().call_soon(self.manager.resolve_wait, request_id, dict(self.reply))


class BrowserRouteTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        conv = ConversationRepo(self.db).create(title="Tee")
        self.conv_id = conv.id
        listing = {"title": "Tee", "category_path": "Clothing > Tops", "ebay_specifics": {"neckline": ""}}
        revision = ListingRepo(self.db).save_revision(conv.id, listing, source="user")
        job = JobRepo(self.db).create(
            conv_id=conv.id,
            approved_revision_id=revision.id,
            listing_snapshot={**listing, "platforms": ["ebay"]},
            vendoo_item_id="draft-123",
            status="completed",
        )
        self.job_id = job.id
        self.manager = ExtensionManager()

        def override_get_db():
            yield self.db

        app.dependency_overrides[get_db] = override_get_db
        self.patches = [
            patch("vendoo_studio.services.extension_connection.extension_manager", self.manager),
        ]
        for item in self.patches:
            item.start()
        self.client = TestClient(app)

    def tearDown(self):
        for item in self.patches:
            item.stop()
        app.dependency_overrides.pop(get_db, None)
        self.db.close()

    def connect(self, reply: dict) -> FakeConnection:
        connection = FakeConnection(self.manager, reply)
        self.manager.connection = connection
        self.manager.paired = True
        return connection

    def test_open_requires_chrome(self):
        response = self.client.post(f"/api/jobs/{self.job_id}/browser/open", json={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Connect Chrome", response.json()["detail"])

    def test_open_sends_draft_and_returns_extension_reply(self):
        connection = self.connect({"ok": True, "tab_id": 7, "controller": "human"})
        response = self.client.post(f"/api/jobs/{self.job_id}/browser/open", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["controller"], "human")
        message = connection.sent[0]
        self.assertEqual(message["type"], "browser.open")
        self.assertEqual(message["payload"]["vendoo_item_id"], "draft-123")
        self.assertEqual(message["payload"]["job_id"], self.job_id)

    def test_open_without_draft_is_rejected(self):
        job = JobRepo(self.db).get(self.job_id)
        job.vendoo_item_id = None
        job.vendoo_url = None
        self.db.commit()
        self.connect({"ok": True})
        response = self.client.post(f"/api/jobs/{self.job_id}/browser/open", json={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Send the listing", response.json()["detail"])

    def test_extension_refusal_becomes_conflict(self):
        self.connect({"ok": False, "error": "Refused to press \"Publish\"."})
        response = self.client.post(f"/api/jobs/{self.job_id}/browser/act", json={"action": "click", "selector": "#publish"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("Publish", response.json()["detail"])

    def test_navigation_forwards_direction_and_rejects_invalid_actions(self):
        connection = self.connect({"ok": True})
        response = self.client.post(f"/api/jobs/{self.job_id}/browser/navigate", json={"direction": "back"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(connection.sent[0]["type"], "browser.navigate")
        self.assertEqual(connection.sent[0]["payload"]["direction"], "back")
        response = self.client.post(f"/api/jobs/{self.job_id}/browser/navigate", json={"direction": "publish"})
        self.assertEqual(response.status_code, 422)

    def test_input_is_bounded(self):
        self.connect({"ok": True})
        too_many = [{"kind": "mouse", "type": "mouseMoved", "x_ratio": 0.5, "y_ratio": 0.5}] * 41
        self.assertEqual(self.client.post(f"/api/jobs/{self.job_id}/browser/input", json={"events": too_many}).status_code, 422)
        outside = [{"kind": "mouse", "type": "mouseMoved", "x_ratio": 1.5, "y_ratio": 0.5}]
        self.assertEqual(self.client.post(f"/api/jobs/{self.job_id}/browser/input", json={"events": outside}).status_code, 422)

    def test_input_is_forwarded_without_waiting(self):
        connection = self.connect({"ok": True})
        events = [{"kind": "key", "type": "down", "key": "Enter", "modifiers": 0}]
        response = self.client.post(f"/api/jobs/{self.job_id}/browser/input", json={"events": events})
        self.assertEqual(response.json(), {"sent": True})
        self.assertEqual(connection.sent[0]["type"], "browser.input")
        self.assertEqual(connection.sent[0]["payload"]["events"][0]["key"], "Enter")

    def test_touch_is_forwarded_and_counts_as_taking_over(self):
        from vendoo_studio.services import browser_bridge

        connection = self.connect({"ok": True})
        before = time.monotonic()
        moved = [{"kind": "touch", "type": "touchMove", "x_ratio": 0.5, "y_ratio": 0.5}]
        self.client.post(f"/api/jobs/{self.job_id}/browser/input", json={"events": moved})
        self.assertFalse(browser_bridge.human_input_since(self.job_id, before))
        pressed = [{"kind": "touch", "type": "touchStart", "x_ratio": 0.5, "y_ratio": 0.5}]
        response = self.client.post(f"/api/jobs/{self.job_id}/browser/input", json={"events": pressed})
        self.assertEqual(response.json(), {"sent": True})
        self.assertEqual(connection.sent[-1]["payload"]["events"][0]["type"], "touchStart")
        self.assertTrue(browser_bridge.human_input_since(self.job_id, before))

    def test_phone_viewport_is_forwarded(self):
        connection = self.connect({"ok": True})
        response = self.client.post(
            f"/api/jobs/{self.job_id}/browser/viewport", json={"width": 390, "height": 640, "scale": 2},
        )
        self.assertEqual(response.json(), {"sent": True})
        self.assertEqual(connection.sent[0]["type"], "browser.viewport")
        self.assertEqual(connection.sent[0]["payload"]["width"], 390)
        self.assertEqual(connection.sent[0]["payload"]["height"], 640)

    def test_phone_viewport_is_bounded(self):
        self.connect({"ok": True})
        for body in ({"width": 100, "height": 640}, {"width": 390, "height": 9000}, {"width": 390, "height": 640, "scale": 8}):
            response = self.client.post(f"/api/jobs/{self.job_id}/browser/viewport", json=body)
            self.assertEqual(response.status_code, 422)


class BrowserResultOverWebSocketTest(unittest.TestCase):
    def test_browser_result_resolves_pending_request(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        manager = ExtensionManager()
        resolved = {}

        async def handshake(ws, *_):
            return True

        original_resolve = manager.resolve_wait

        def record(request_id, payload):
            resolved[request_id] = payload
            original_resolve(request_id, payload)

        with patch("vendoo_studio.services.extension_connection.SessionLocal", Session), \
             patch("vendoo_studio.services.extension_connection.extension_manager", manager), \
             patch.object(manager, "verify_token", return_value=True), \
             patch.object(manager, "resolve_wait", side_effect=record), \
             patch("vendoo_studio.services.extension_connection._websocket_allowed", return_value=True), \
             patch("vendoo_studio.services.extension_connection.handshake_extension", side_effect=handshake), \
             patch("vendoo_studio.services.extension_connection.dispatch_queued_jobs", AsyncMock()):
            client = TestClient(app)
            with client.websocket_connect("/api/extension/ws") as ws:
                ws.send_json({"type": "extension.ready", "payload": {"token": "test"}})
                ws.send_json({"type": "browser.result", "payload": {"request_id": "abc", "ok": True, "fields": []}})
                ws.send_json({"type": "pong"})
                for _ in range(50):
                    if "abc" in resolved:
                        break
                    client.get("/api/health")
        self.assertEqual(resolved["abc"]["fields"], [])


class PreviewFrameForFinishedDraftTest(unittest.TestCase):
    def test_frames_stream_for_completed_job_without_late_result_events(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        conv = ConversationRepo(db).create(title="Tee")
        revision = ListingRepo(db).save_revision(conv.id, {"title": "Tee"}, source="user")
        job = JobRepo(db).create(conv_id=conv.id, approved_revision_id=revision.id, listing_snapshot={"title": "Tee"},
                                 vendoo_item_id="draft-1", status="completed")
        job_id = job.id
        manager = ExtensionManager()
        published = []

        async def handshake(ws, *_):
            return True

        async def publish(key, frame):
            published.append((key, frame))

        with patch("vendoo_studio.services.extension_connection.SessionLocal", Session), \
             patch("vendoo_studio.services.extension_connection.extension_manager", manager), \
             patch.object(manager, "verify_token", return_value=True), \
             patch("vendoo_studio.services.extension_connection._websocket_allowed", return_value=True), \
             patch("vendoo_studio.services.extension_connection.handshake_extension", side_effect=handshake), \
             patch("vendoo_studio.services.extension_connection.dispatch_queued_jobs", AsyncMock()), \
             patch("vendoo_studio.services.preview_hub.preview_hub.publish", side_effect=publish):
            client = TestClient(app)
            with client.websocket_connect("/api/extension/ws") as ws:
                ws.send_json({"type": "extension.ready", "payload": {"token": "test"}})
                ws.send_json({"type": "job.preview_frame", "job_id": job_id, "payload": {
                    "mime": "image/jpeg", "data": "abc", "url": "https://web.vendoo.co/app/item/draft-1",
                    "viewport_width": 1280, "viewport_height": 800,
                }})
                for _ in range(50):
                    if published:
                        break
                    client.get("/api/health")
        events = [event.event_type for event in JobRepo(Session()).get_events(job_id)]
        db.close()
        self.assertEqual(published[0][0], job_id)
        self.assertEqual(published[0][1]["viewport_width"], 1280)
        self.assertNotIn("ignored_late_result", events)


class FinishedJobRepliesTest(unittest.TestCase):
    """Sent listings are still read and updated through their finished job."""

    def _run(self, status: str, wait: bool):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        conv = ConversationRepo(db).create(title="Tee")
        revision = ListingRepo(db).save_revision(conv.id, {"title": "Tee"}, source="user")
        job = JobRepo(db).create(conv_id=conv.id, approved_revision_id=revision.id, listing_snapshot={"title": "Tee"},
                                 vendoo_item_id="draft-1", status=status)
        job_id = job.id
        db.close()
        manager = ExtensionManager()
        resolved = {}

        async def handshake(ws, *_):
            if wait:
                future = manager.register_wait("req-1", job_id)
                future.add_done_callback(lambda f: resolved.setdefault("req-1", f.result()))
            return True

        with patch("vendoo_studio.services.extension_connection.SessionLocal", Session), \
             patch("vendoo_studio.services.extension_connection.extension_manager", manager), \
             patch.object(manager, "verify_token", return_value=True), \
             patch("vendoo_studio.services.extension_connection._websocket_allowed", return_value=True), \
             patch("vendoo_studio.services.extension_connection.handshake_extension", side_effect=handshake), \
             patch("vendoo_studio.services.extension_connection.dispatch_queued_jobs", AsyncMock()):
            client = TestClient(app)
            with client.websocket_connect("/api/extension/ws") as ws:
                ws.send_json({"type": "extension.ready", "payload": {"token": "test"}})
                ws.send_json({"type": "job.vendoo_api_result", "job_id": job_id, "message_id": "req-1", "payload": {
                    "request_id": "req-1", "ok": True, "results": [{"op": "get_item", "ok": True, "item": {"itemID": "draft-1"}}],
                }})
                ws.send_json({"type": "pong"})
                for _ in range(50):
                    if resolved:
                        break
                    client.get("/api/health")
        events = [event.event_type for event in JobRepo(Session()).get_events(job_id)]
        return resolved, events

    def test_reply_reaches_waiter_for_completed_job(self):
        resolved, events = self._run("completed", wait=True)
        self.assertEqual(resolved["req-1"]["results"][0]["item"]["itemID"], "draft-1")
        self.assertNotIn("ignored_late_result", events)

    def test_unrequested_reply_for_completed_job_is_dropped(self):
        resolved, events = self._run("completed", wait=False)
        self.assertEqual(resolved, {})
        self.assertIn("ignored_late_result", events)


class FrameViewportTest(unittest.TestCase):
    def test_viewport_dimensions_pass_through_when_sane(self):
        frame = sanitize_frame({"mime": "image/jpeg", "data": "abc", "viewport_width": 1280, "viewport_height": 800})
        self.assertEqual((frame["viewport_width"], frame["viewport_height"]), (1280, 800))
        frame = sanitize_frame({"mime": "image/jpeg", "data": "abc", "viewport_width": True, "viewport_height": -5})
        self.assertEqual((frame["viewport_width"], frame["viewport_height"]), (None, None))


if __name__ == "__main__":
    unittest.main()
