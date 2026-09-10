from __future__ import annotations

import asyncio
import unittest

from fastapi.testclient import TestClient

from vendoo_studio.services.preview_hub import (
    MAX_FRAME_CHARS,
    PreviewHub,
    sanitize_frame,
)


class SanitizeFrameTest(unittest.TestCase):
    def test_accepts_jpeg_https_url(self):
        frame = sanitize_frame({
            "mime": "image/jpeg",
            "data": "abc123",
            "url": "https://web.vendoo.co/app/item/new",
            "width": 1024,
            "height": 720,
        }, "filling_general")
        self.assertEqual(frame["mime"], "image/jpeg")
        self.assertEqual(frame["data"], "abc123")
        self.assertEqual(frame["url"], "https://web.vendoo.co/app/item/new")
        self.assertEqual(frame["step"], "filling_general")
        self.assertEqual(frame["width"], 1024)

    def test_rejects_non_jpeg_and_oversized_payloads(self):
        self.assertIsNone(sanitize_frame({"mime": "image/png", "data": "abc"}))
        self.assertIsNone(sanitize_frame({"mime": "image/jpeg", "data": ""}))
        self.assertIsNone(sanitize_frame({"mime": "image/jpeg", "data": "x" * (MAX_FRAME_CHARS + 1)}))

    def test_accepts_full_viewport_jpeg_payload(self):
        frame = sanitize_frame({
            "mime": "image/jpeg",
            "data": "x" * 400_000,
            "url": "https://web.vendoo.co/app/item/new",
        })
        self.assertIsNotNone(frame)
        self.assertEqual(len(frame["data"]), 400_000)

    def test_drops_non_https_urls(self):
        frame = sanitize_frame({
            "mime": "image/jpeg",
            "data": "abc",
            "url": "http://127.0.0.1:4318/secret",
        })
        self.assertEqual(frame["url"], "")


class PreviewHubTest(unittest.IsolatedAsyncioTestCase):
    async def test_subscriber_receives_latest_frame_only(self):
        hub = PreviewHub()
        queue = await hub.subscribe("job-1")
        await hub.publish("job-1", {"data": "first"})
        await hub.publish("job-1", {"data": "second"})
        frame = await asyncio.wait_for(queue.get(), timeout=1)
        self.assertEqual(frame["data"], "second")
        self.assertTrue(queue.empty())
        await hub.unsubscribe("job-1", queue)

    async def test_late_subscriber_gets_current_frame(self):
        hub = PreviewHub()
        await hub.publish("job-1", {"data": "live"})
        queue = await hub.subscribe("job-1")
        frame = await asyncio.wait_for(queue.get(), timeout=1)
        self.assertEqual(frame["data"], "live")
        await hub.unsubscribe("job-1", queue)


class PreviewRouteTest(unittest.TestCase):
    def test_preview_route_returns_job_not_found(self):
        from vendoo_studio.main import app

        client = TestClient(app)
        response = client.get("/api/jobs/missing/preview")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Job not found")


if __name__ == "__main__":
    unittest.main()
