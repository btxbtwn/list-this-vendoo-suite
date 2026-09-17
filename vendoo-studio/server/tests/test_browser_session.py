"""Interactive Vendoo browser: routes, WebSocket replies, and directed fills."""
from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.routes.extension import ExtensionManager
from vendoo_studio.services.browser_direct import restrict_patches, split_targets
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


class Provider:
    def __init__(self, text: str):
        self.text = text

    async def chat(self, messages, stream=True):
        yield self.text


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
            patch("vendoo_studio.routes.extension.extension_manager", self.manager),
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

    def test_direct_fill_saves_only_targeted_values_and_applies(self):
        self.connect({"ok": True})
        reply = json.dumps({"missing_fields": [
            {"marketplace": "ebay", "field": "Neckline", "value": "Crew Neck"},
            {"marketplace": "ebay", "field": "Brand", "value": "Invented"},
        ]})
        apply = AsyncMock(return_value=(True, None))
        with patch("vendoo_studio.services.listing_provider.get_listing_provider", return_value=Provider(reply)), \
             patch("vendoo_studio.services.auto_apply.apply_patches", apply), \
             patch("vendoo_studio.database.SessionLocal", self.Session):
            response = self.client.post(f"/api/jobs/{self.job_id}/browser/direct", json={
                "note": "It is a crew neck",
                "targets": [
                    {"marketplace": "ebay", "field": "Neckline", "value": "", "selector": "#listings\\.ebay\\.neckline"},
                    {"marketplace": "ebay", "field": "Return Policy", "value": ""},
                ],
            })
        body = response.json()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(body["ok"])
        self.assertEqual(body["patches"], [{
            "marketplace": "ebay",
            "field": "Neckline",
            "value": "Crew Neck",
            "selector": "#listings\\.ebay\\.neckline",
        }])
        self.assertEqual([item["field"] for item in body["skipped"]], ["Return Policy"])
        latest = ListingRepo(self.db).get_revisions(self.conv_id)[0]
        self.assertEqual(latest.source, "browser_direct")
        self.assertEqual(latest.listing_json["ebay_specifics"]["neckline"], "Crew Neck")
        self.assertNotEqual(latest.listing_json.get("brand"), "Invented")
        texts = [message.text for message in ConversationRepo(self.db).get_messages(self.conv_id)]
        self.assertTrue(any("crew neck" in text for text in texts))
        self.assertEqual(apply.await_args.args[3][0]["value"], "Crew Neck")

    def test_direct_fill_waits_for_running_job(self):
        job = JobRepo(self.db).get(self.job_id)
        job.status = "dispatched"
        self.db.commit()
        self.connect({"ok": True})
        response = self.client.post(f"/api/jobs/{self.job_id}/browser/direct", json={
            "targets": [{"marketplace": "ebay", "field": "Neckline"}],
        })
        self.assertEqual(response.status_code, 409)


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

        with patch("vendoo_studio.routes.extension.SessionLocal", Session), \
             patch("vendoo_studio.routes.extension.extension_manager", manager), \
             patch.object(manager, "verify_token", return_value=True), \
             patch.object(manager, "resolve_wait", side_effect=record), \
             patch("vendoo_studio.routes.extension._websocket_allowed", return_value=True), \
             patch("vendoo_studio.routes.extension.handshake_extension", side_effect=handshake), \
             patch("vendoo_studio.routes.extension.dispatch_queued_jobs", AsyncMock()):
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

        with patch("vendoo_studio.routes.extension.SessionLocal", Session), \
             patch("vendoo_studio.routes.extension.extension_manager", manager), \
             patch.object(manager, "verify_token", return_value=True), \
             patch("vendoo_studio.routes.extension._websocket_allowed", return_value=True), \
             patch("vendoo_studio.routes.extension.handshake_extension", side_effect=handshake), \
             patch("vendoo_studio.routes.extension.dispatch_queued_jobs", AsyncMock()), \
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


class DirectTargetsTest(unittest.TestCase):
    def test_split_targets_dedupes_and_skips_account_settings(self):
        fillable, skipped = split_targets([
            {"marketplace": "ebay", "field": "Neckline", "options": ["Crew Neck", "V-Neck"]},
            {"marketplace": "EBAY", "field": "neckline"},
            {"marketplace": "depop", "field": "Parcel Size"},
            {"marketplace": "poshmark", "field": "Shipping Discount"},
            {"marketplace": "ebay", "field": "Anything", "account_managed": True},
            {"marketplace": "amazon", "field": "Title"},
        ])
        self.assertEqual([(t["marketplace"], t["field"]) for t in fillable], [("ebay", "Neckline"), ("depop", "Parcel Size")])
        self.assertEqual(fillable[0]["options"], ["Crew Neck", "V-Neck"])
        self.assertEqual({s["field"] for s in skipped}, {"Shipping Discount", "Anything"})

    def test_restrict_patches_drops_unchanged_and_unrequested(self):
        targets, _ = split_targets([
            {"marketplace": "general", "field": "Color", "value": "Blue", "selector": "#color"},
            {"marketplace": "ebay", "field": "Season", "value": ""},
        ])
        patches = restrict_patches([
            {"marketplace": "general", "field": "color", "value": "Blue"},
            {"marketplace": "ebay", "field": "Season", "value": ["Summer"]},
            {"marketplace": "ebay", "field": "Brand", "value": "Nike"},
        ], targets)
        self.assertEqual(patches, [{"marketplace": "ebay", "field": "Season", "value": "Summer", "selector": ""}])


class FrameViewportTest(unittest.TestCase):
    def test_viewport_dimensions_pass_through_when_sane(self):
        frame = sanitize_frame({"mime": "image/jpeg", "data": "abc", "viewport_width": 1280, "viewport_height": 800})
        self.assertEqual((frame["viewport_width"], frame["viewport_height"]), (1280, 800))
        frame = sanitize_frame({"mime": "image/jpeg", "data": "abc", "viewport_width": True, "viewport_height": -5})
        self.assertEqual((frame["viewport_width"], frame["viewport_height"]), (None, None))


if __name__ == "__main__":
    unittest.main()
