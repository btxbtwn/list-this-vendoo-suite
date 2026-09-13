from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
