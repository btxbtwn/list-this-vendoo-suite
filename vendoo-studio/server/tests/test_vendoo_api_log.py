"""Redacted Vendoo API log ring and the Settings routes that read it."""

from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient

from vendoo_studio.main import app
from vendoo_studio.services.vendoo_api_log import clear, ingest, list_entries, record, sanitize_entry


class SanitizeTest(unittest.TestCase):
    def tearDown(self):
        clear()

    def test_query_strings_and_token_text_never_land(self):
        entry = sanitize_entry({
            "method": "GET",
            "host": "api.web.vendoo.co",
            "path": "/api/item/abc?userId=SECRET&key=nope",
            "status": 200,
            "ok": True,
            "duration_ms": 12,
            "error": "Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
            "at": "2026-09-27T04:00:00Z",
        })
        self.assertIsNotNone(entry)
        blob = json.dumps(entry)
        self.assertNotIn("SECRET", blob)
        self.assertNotIn("Bearer", blob)
        self.assertNotIn("eyJ", blob)
        self.assertEqual(entry["path"], "/api/item/abc")
        self.assertTrue(entry["ok"])
        self.assertIsNone(entry["error"])

    def test_failures_keep_a_status_line_only(self):
        entry = sanitize_entry({
            "method": "POST",
            "host": "us-central1-vendoo-prod-7948f.cloudfunctions.net",
            "path": "/items",
            "status": 500,
            "ok": False,
            "error": "createItem returned the whole listing body",
        })
        self.assertEqual(entry["error"], "HTTP 500")
        self.assertFalse(entry["ok"])
        self.assertNotIn("listing", entry["error"])

    def test_signed_upload_query_and_userinfo_are_dropped(self):
        signed = sanitize_entry({
            "method": "PUT",
            "host": "storage.googleapis.com",
            "path": "/bucket/object?X-Goog-Signature=abc&token=xyz",
            "status": 200,
            "ok": True,
        })
        self.assertEqual(signed["path"], "/bucket/object")
        self.assertIsNone(sanitize_entry({
            "method": "GET",
            "host": "user:secret@api.web.vendoo.co",
            "path": "/api/item/abc",
            "status": 200,
            "ok": True,
        }))

    def test_ring_keeps_the_newest_two_hundred(self):
        record([
            {"method": "GET", "host": "api.web.vendoo.co", "path": f"/api/item/{i}", "status": 200, "ok": True}
            for i in range(205)
        ])
        entries = list_entries()
        self.assertEqual(len(entries), 200)
        self.assertEqual(entries[0]["path"], "/api/item/204")
        self.assertEqual(entries[-1]["path"], "/api/item/5")

    def test_ingest_reads_a_batched_payload(self):
        stored = ingest({"entries": [
            {"method": "POST", "host": "securetoken.googleapis.com", "path": "/v1/token", "status": 200, "ok": True},
            "not-an-entry",
        ]})
        self.assertEqual(stored, 1)
        self.assertEqual(list_entries()[0]["host"], "securetoken.googleapis.com")


class RouteTest(unittest.TestCase):
    def setUp(self):
        clear()
        self.client = TestClient(app)

    def tearDown(self):
        clear()

    def test_get_and_clear(self):
        record([{
            "method": "GET",
            "host": "api.web.vendoo.co",
            "path": "/api/item/abc?userId=SECRET",
            "status": 200,
            "ok": True,
            "duration_ms": 8,
        }])
        listed = self.client.get("/api/settings/vendoo-api-logs")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["entries"][0]["path"], "/api/item/abc")
        self.assertNotIn("SECRET", listed.text)
        cleared = self.client.delete("/api/settings/vendoo-api-logs")
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(self.client.get("/api/settings/vendoo-api-logs").json()["entries"], [])
