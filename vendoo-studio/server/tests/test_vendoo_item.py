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


class VendooItemRouteTest(unittest.TestCase):
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
        for request_id in list(extension_manager._waits):
            extension_manager.cancel_wait(request_id)
        self.db.close()

    def _connect_chrome(self):
        extension_manager.connection = MagicMock()
        extension_manager.paired = True

    def test_vendoo_item_returns_draft_json(self):
        self._connect_chrome()

        async def fake_dispatch(job, request_id):
            extension_manager.resolve_wait(request_id, {
                "ok": True,
                "source": "api+form",
                "item_id": "abc123",
                "url": "https://web.vendoo.co/app/item/abc123",
                "item": {
                    "itemID": "abc123",
                    "generalDetails": {"title": "Nike tee"},
                    "listings": {
                        "ebay": {"status": {"listed": True}},
                        "depop": {"status": {"listed": False}},
                    },
                },
                "form": {"generalDetails": {"title": "Nike tee"}},
                "statuses": {
                    "general": "COMPLETE",
                    "ebay": "LISTED",
                    "depop": "NOT LISTED",
                },
            })
            return True

        with patch("vendoo_studio.routes.extension.dispatch_vendoo_get", new=AsyncMock(side_effect=fake_dispatch)):
            response = self.client.post(f"/api/jobs/{self.job.id}/vendoo-item")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["source"], "api+form")
        self.assertEqual(body["item"]["generalDetails"]["title"], "Nike tee")
        self.assertEqual(body["form"]["generalDetails"]["title"], "Nike tee")
        self.assertEqual(body["statuses"]["ebay"], "LISTED")
        self.assertEqual(body["statuses"]["depop"], "NOT LISTED")
        self.assertEqual(body["statuses"]["general"], "COMPLETE")

        cached = self.client.post(f"/api/jobs/{self.job.id}/vendoo-item")
        self.assertEqual(cached.status_code, 200, cached.text)
        self.assertEqual(cached.json()["statuses"]["ebay"], "LISTED")

    def test_vendoo_item_requires_connected_chrome(self):
        response = self.client.post(f"/api/jobs/{self.job.id}/vendoo-item")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Chrome is not connected", response.json()["detail"])

    def test_vendoo_item_requires_draft(self):
        self._connect_chrome()
        self.job.vendoo_url = None
        self.job.vendoo_item_id = None
        self.db.commit()
        response = self.client.post(f"/api/jobs/{self.job.id}/vendoo-item")
        self.assertEqual(response.status_code, 400)
        self.assertIn("No Vendoo draft", response.json()["detail"])

    def test_vendoo_item_job_not_found(self):
        self._connect_chrome()
        response = self.client.post("/api/jobs/missing/vendoo-item")
        self.assertEqual(response.status_code, 404)

    def test_vendoo_item_read_failure(self):
        self._connect_chrome()

        async def fake_dispatch(job, request_id):
            extension_manager.resolve_wait(request_id, {
                "ok": False,
                "error": "GET /api/item returned 401",
            })
            return True

        with patch("vendoo_studio.routes.extension.dispatch_vendoo_get", new=AsyncMock(side_effect=fake_dispatch)):
            response = self.client.post(f"/api/jobs/{self.job.id}/vendoo-item")

        self.assertEqual(response.status_code, 502)
        self.assertIn("401", response.json()["detail"])

    def test_vendoo_item_refresh_failure_does_not_return_stale_cache(self):
        self._connect_chrome()

        async def ok_dispatch(job, request_id):
            extension_manager.resolve_wait(request_id, {
                "ok": True,
                "source": "api+form",
                "item_id": "abc123",
                "url": "https://web.vendoo.co/app/item/abc123",
                "item": {"itemID": "abc123", "generalDetails": {"title": "Old title"}},
                "form": {"generalDetails": {"title": "Old title"}},
            })
            return True

        async def fail_dispatch(job, request_id):
            extension_manager.resolve_wait(request_id, {
                "ok": False,
                "error": "Tab closed during refresh",
            })
            return True

        with patch("vendoo_studio.routes.extension.dispatch_vendoo_get", new=AsyncMock(side_effect=ok_dispatch)):
            primed = self.client.post(f"/api/jobs/{self.job.id}/vendoo-item")
        self.assertEqual(primed.status_code, 200, primed.text)

        with patch("vendoo_studio.routes.extension.dispatch_vendoo_get", new=AsyncMock(side_effect=fail_dispatch)):
            response = self.client.post(f"/api/jobs/{self.job.id}/vendoo-item?refresh=true")

        self.assertEqual(response.status_code, 502, response.text)
        self.assertIn("Tab closed", response.json()["detail"])

    def test_vendoo_item_times_out(self):
        self._connect_chrome()

        with patch("vendoo_studio.routes.extension.VENDOO_GET_TIMEOUT_SEC", 0.05), patch(
            "vendoo_studio.routes.extension.dispatch_vendoo_get",
            new=AsyncMock(return_value=True),
        ):
            response = self.client.post(f"/api/jobs/{self.job.id}/vendoo-item")

        self.assertEqual(response.status_code, 504)
        self.assertIn("did not return", response.json()["detail"])


class ResolveCategoryRouteTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        self.db = Session()
        self.conv = Conversation(title="Sweatshirt")
        self.db.add(self.conv)
        self.db.commit()
        self.job = Job(
            conversation_id=self.conv.id,
            approved_revision_id="rev1",
            listing_snapshot={"title": "Fruit of the Loom Sweatshirt", "category_path": "T-Shirts"},
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
        for request_id in list(extension_manager._waits):
            extension_manager.cancel_wait(request_id)
        self.db.close()

    def _connect_chrome(self):
        extension_manager.connection = MagicMock()
        extension_manager.paired = True

    def test_resolve_category_saves_picker_path(self):
        self._connect_chrome()
        path = "Clothing, Shoes & Accessories > Men > Men's Clothing > Sweats & Hoodies > Sweatshirts"

        async def fake_resolve(db, conv_id, query=None, job=None):
            return {"ok": True, "query": "Men Sweatshirt", "path": path, "matches": [{"path": path}]}

        with patch(
            "vendoo_studio.services.category_lookup.resolve_listing_category",
            new=AsyncMock(side_effect=fake_resolve),
        ):
            response = self.client.post(f"/api/jobs/{self.job.id}/resolve-category", json={"query": "Men Sweatshirt"})

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["path"], path)

    def test_resolve_category_requires_chrome(self):
        response = self.client.post(f"/api/jobs/{self.job.id}/resolve-category", json={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Chrome is not connected", response.json()["detail"])

    def test_resolve_category_blocks_active_fill(self):
        self._connect_chrome()
        self.job.status = "dispatched"
        self.job.current_step = "filling_fields"
        self.db.commit()
        response = self.client.post(f"/api/jobs/{self.job.id}/resolve-category", json={})
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
