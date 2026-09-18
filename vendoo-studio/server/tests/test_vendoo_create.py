from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from vendoo_studio.services import vendoo_create
from vendoo_studio.services.vendoo_create import VendooCreateError, create_item, load_schema, probe_schema


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


JOB = SimpleNamespace(id="job-1", conversation_id="conv-1")
PHOTOS = [
    SimpleNamespace(id="p1", mime_type="image/jpeg", width=1600, height=1200),
    SimpleNamespace(id="p2", mime_type="image/png", width=800, height=900),
]
LISTING = {"title": "Levi's 501", "description": "Classic", "price": 48, "condition": "Pre-Owned - Good"}
PROBED = {"generalDetails": {"condition": {"value": "v_pre_owned_good", "displayName": "Pre-Owned - Good"}}, "itemID": "old1"}


class FakeBridge:
    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []

    async def request(self, job, message_type, payload=None, *, timeout=0):
        self.sent.append((message_type, payload))
        return self.replies.pop(0)


class _TmpSchema(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(vendoo_create, "schema_path", lambda: Path(self.tmp.name) / "schema.json")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()


class ProbeTest(_TmpSchema):
    def test_learns_and_persists_merged_schema(self):
        fake = FakeBridge([
            {"ok": True, "results": [{"op": "get_item", "ok": True, "item_id": "old1", "item": PROBED},
                                     {"op": "get_item", "ok": False, "item_id": "old2", "error": "404"}]},
        ])
        with mock.patch.object(vendoo_create.browser_bridge, "request", fake.request):
            out = run(probe_schema(JOB, ["old1", "old2"]))
        self.assertEqual(out["learned_from"], 1)
        self.assertEqual(out["failures"], [{"item_id": "old2", "error": "404"}])
        self.assertEqual(out["schema"]["fields"]["condition"]["labels"]["pre owned good"], "v_pre_owned_good")
        self.assertEqual(load_schema()["item_count"], 1)
        ops = fake.sent[0][1]["ops"]
        self.assertEqual([op["op"] for op in ops], ["get_item", "get_item"])

        # A second probe widens rather than replaces.
        fake2 = FakeBridge([{"ok": True, "results": [{"op": "get_item", "ok": True, "item": {
            "generalDetails": {"condition": {"value": "v_new", "displayName": "New With Tags/Box"}}}}]}])
        with mock.patch.object(vendoo_create.browser_bridge, "request", fake2.request):
            run(probe_schema(JOB, ["old3"]))
        labels = load_schema()["fields"]["condition"]["labels"]
        self.assertEqual(set(labels), {"pre owned good", "new with tags box"})
        self.assertEqual(load_schema()["item_count"], 2)

    def test_requires_ids(self):
        with self.assertRaises(VendooCreateError):
            run(probe_schema(JOB, []))


class CreateTest(_TmpSchema):
    def _replies(self):
        return [
            {"ok": True, "uid": "u1", "results": [
                {"op": "session", "ok": True, "uid": "u1"},
                {"op": "new_item_id", "ok": True, "item_id": "NEWid1234567890abcde"},
                {"op": "subscription", "ok": True, "version": "v2"},
                {"op": "upload_photo", "ok": True, "photo_id": "p1", "image": {"version": 3, "id": "images/u1/a.jpg", "originalMaxDimension": 1600}},
                {"op": "upload_photo", "ok": True, "photo_id": "p2", "image": {"version": 3, "id": "images/u1/b.png", "originalMaxDimension": 900}},
            ]},
            {"ok": True, "uid": "u1", "results": [
                {"op": "create_item", "ok": True, "result": {"ok": True}},
                {"op": "get_item", "ok": True, "item_id": "NEWid1234567890abcde", "item": {
                    "itemID": "NEWid1234567890abcde",
                    "generalDetails": {"title": "Levi's 501", "description": "Classic", "price": 48,
                                       "condition": {"value": "v_pre_owned_good", "displayName": "Pre-Owned - Good"}},
                }},
            ]},
        ]

    def test_creates_item_and_verifies(self):
        Path(self.tmp.name, "schema.json").write_text(json.dumps({"fields": {"condition": {
            "labels": {"pre owned good": "v_pre_owned_good"}, "codes": ["v_pre_owned_good"], "shape": "object"}}, "item_count": 1}))
        fake = FakeBridge(self._replies())
        with mock.patch.object(vendoo_create.browser_bridge, "request", fake.request):
            out = run(create_item(JOB, LISTING, PHOTOS))

        self.assertEqual(out["item_id"], "NEWid1234567890abcde")
        self.assertEqual(out["url"], "https://web.vendoo.co/app/item/NEWid1234567890abcde")
        self.assertEqual(out["unresolved"], [])
        self.assertEqual(out["diff"], [])

        prep_ops = fake.sent[0][1]["ops"]
        self.assertEqual([op["op"] for op in prep_ops], ["session", "new_item_id", "subscription", "upload_photo", "upload_photo"])
        self.assertEqual(prep_ops[3]["photo"]["url"], "http://127.0.0.1:4318/api/jobs/job-1/photos/p1")
        self.assertEqual(prep_ops[3]["photo"]["extension"], "jpg")
        self.assertEqual(prep_ops[4]["photo"]["extension"], "png")
        self.assertEqual(prep_ops[4]["photo"]["max_dimension"], 900)

        create_ops = fake.sent[1][1]["ops"]
        self.assertEqual(create_ops[0]["op"], "create_item")
        self.assertEqual(create_ops[0]["subscription_version"], "v2")
        item = create_ops[0]["item"]
        self.assertEqual(item["itemID"], "NEWid1234567890abcde")
        self.assertEqual(item["userID"], "u1")
        self.assertEqual(item["generalDetails"]["condition"]["value"], "v_pre_owned_good")
        self.assertEqual([img["id"] for img in item["generalDetails"]["images"]], ["images/u1/a.jpg", "images/u1/b.png"])
        self.assertEqual(create_ops[1], {"op": "get_item", "item_id": "NEWid1234567890abcde"})

    def test_reports_unresolved_and_diff(self):
        replies = self._replies()
        replies[1]["results"][1]["item"]["generalDetails"]["price"] = 50
        fake = FakeBridge(replies)
        with mock.patch.object(vendoo_create.browser_bridge, "request", fake.request):
            out = run(create_item(JOB, LISTING, PHOTOS))
        self.assertEqual([u["field"] for u in out["unresolved"]], ["condition"])
        # Vendoo turning our plain label into its coded object is not a mismatch;
        # the changed price is.
        self.assertEqual([d["field"] for d in out["diff"]], ["price"])

    def test_failed_upload_stops_before_create(self):
        replies = self._replies()
        replies[0] = {"ok": False, "results": [
            {"op": "session", "ok": True, "uid": "u1"},
            {"op": "new_item_id", "ok": True, "item_id": "x"},
            {"op": "subscription", "ok": True, "version": None},
            {"op": "upload_photo", "ok": False, "error": "Vendoo image slot returned 401"},
        ]}
        fake = FakeBridge(replies)
        with mock.patch.object(vendoo_create.browser_bridge, "request", fake.request), self.assertRaises(VendooCreateError) as ctx:
            run(create_item(JOB, LISTING, PHOTOS))
        self.assertIn("401", str(ctx.exception))
        self.assertEqual(len(fake.sent), 1)

    def test_needs_photos(self):
        with self.assertRaises(VendooCreateError):
            run(create_item(JOB, LISTING, []))


if __name__ == "__main__":
    unittest.main()
