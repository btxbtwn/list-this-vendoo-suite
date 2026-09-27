from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.models.conversation import Conversation
from vendoo_studio.models.job import Job
from vendoo_studio.models.listing import Listing, ListingRevision  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.routes.extension import extension_manager


class OpenListingRouteTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        self.db = Session()
        self.conv = Conversation(title="Nike tee")
        self.db.add(self.conv)
        self.db.commit()
        self.job = Job(
            conversation_id=self.conv.id,
            approved_revision_id="rev1",
            listing_snapshot={"title": "Nike tee"},
            status="completed",
            vendoo_url="https://web.vendoo.co/app/item/abc123",
            vendoo_item_id="abc123",
        )
        self.db.add(self.job)
        self.db.commit()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        extension_manager.connection = None
        extension_manager.paired = False

    def tearDown(self):
        app.dependency_overrides.clear()
        extension_manager.connection = None
        extension_manager.paired = False
        self.db.close()

    def _connect_chrome(self):
        extension_manager.connection = MagicMock()
        extension_manager.paired = True

    def test_open_listing_uses_extension_when_connected(self):
        self._connect_chrome()
        with patch(
            "vendoo_studio.routes.extension.dispatch_open_listing",
            new=AsyncMock(return_value=True),
        ) as dispatch, patch(
            "vendoo_studio.services.chrome_bridge.launch_studio_chrome",
        ) as launch:
            response = self.client.post(f"/api/jobs/{self.job.id}/open")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["via"], "extension")
        self.assertEqual(body["url"], "https://web.vendoo.co/app/item/abc123")
        dispatch.assert_awaited()
        launch.assert_not_called()

    def test_open_listing_launches_chrome_when_extension_offline(self):
        with patch("vendoo_studio.services.chrome_bridge.launch_studio_chrome") as launch:
            launch.return_value = {"ok": True}
            response = self.client.post(f"/api/jobs/{self.job.id}/open")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["via"], "chrome")
        launch.assert_called_once_with("https://web.vendoo.co/app/item/abc123", visible=True)

    def test_open_listing_builds_url_from_item_id(self):
        self.job.vendoo_url = None
        self.db.commit()
        with patch("vendoo_studio.services.chrome_bridge.launch_studio_chrome") as launch:
            launch.return_value = {"ok": True}
            response = self.client.post(f"/api/jobs/{self.job.id}/open")

        self.assertEqual(response.status_code, 200, response.text)
        launch.assert_called_once_with("https://web.vendoo.co/app/item/abc123", visible=True)

    def test_open_listing_requires_draft(self):
        self.job.vendoo_url = None
        self.job.vendoo_item_id = None
        self.db.commit()
        response = self.client.post(f"/api/jobs/{self.job.id}/open")
        self.assertEqual(response.status_code, 400)
        self.assertIn("No Vendoo draft", response.json()["detail"])

    def test_open_listing_job_not_found(self):
        response = self.client.post("/api/jobs/missing/open")
        self.assertEqual(response.status_code, 404)

    def test_open_listing_falls_back_when_extension_send_fails(self):
        self._connect_chrome()
        with patch(
            "vendoo_studio.routes.extension.dispatch_open_listing",
            new=AsyncMock(return_value=False),
        ), patch("vendoo_studio.services.chrome_bridge.launch_studio_chrome") as launch:
            launch.return_value = {"ok": True}
            response = self.client.post(f"/api/jobs/{self.job.id}/open")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["via"], "chrome")
        launch.assert_called_once()


class DispatchOpenListingTest(unittest.IsolatedAsyncioTestCase):
    """Open listing counts only when the extension says the tab is showing."""

    def setUp(self):
        self.job = MagicMock(id="job1", vendoo_item_id="abc123", vendoo_url=None)
        self.sent: list[dict] = []
        extension_manager.paired = True

    def tearDown(self):
        extension_manager.connection = None
        extension_manager.paired = False

    def _connection(self, *, reply: dict | None = None, hang: bool = False):
        connection = MagicMock()

        async def send_json(message):
            if hang:
                await asyncio.Event().wait()
            self.sent.append(message)
            if reply is not None:
                request_id = message["payload"]["request_id"]
                asyncio.get_running_loop().call_soon(
                    extension_manager.resolve_wait, request_id, {**reply, "request_id": request_id},
                )

        connection.send_json = send_json
        connection.close = AsyncMock()
        extension_manager.connection = connection
        return connection

    async def test_opened_when_the_extension_confirms(self):
        from vendoo_studio.routes.extension import dispatch_open_listing

        self._connection(reply={"ok": True})
        self.assertTrue(await dispatch_open_listing(self.job))
        self.assertEqual(self.sent[0]["type"], "job.open_listing")

    async def test_not_opened_when_the_extension_reports_failure(self):
        from vendoo_studio.routes.extension import dispatch_open_listing

        self._connection(reply={"ok": False, "error": "no window"})
        self.assertFalse(await dispatch_open_listing(self.job))

    async def test_not_opened_when_the_extension_never_answers(self):
        from vendoo_studio.routes.extension import dispatch_open_listing

        self._connection()
        with patch("vendoo_studio.routes.extension.OPEN_LISTING_TIMEOUT_SEC", 0.05):
            self.assertFalse(await dispatch_open_listing(self.job))
        self.assertEqual(extension_manager._waits, {})

    async def test_a_send_that_never_goes_out_gives_up_and_drops_the_socket(self):
        from vendoo_studio.routes.extension import dispatch_open_listing

        connection = self._connection(hang=True)
        with patch("vendoo_studio.routes.extension.SEND_TIMEOUT_SEC", 0.05):
            self.assertFalse(await dispatch_open_listing(self.job))
        self.assertFalse(extension_manager.connected)
        connection.close.assert_awaited()


if __name__ == "__main__":
    unittest.main()
