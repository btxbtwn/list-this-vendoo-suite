from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.models.conversation import Conversation
from vendoo_studio.models.fill_log import FillLogEntry
from vendoo_studio.models.job import Job
from vendoo_studio.models.listing import Listing, ListingRevision  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.services.fill_log import FillLogService


class FillFieldsRouteTest(unittest.TestCase):
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
            listing_snapshot={"title": "Nike tee", "ebay_specifics": {}},
            status="completed",
            vendoo_url="https://web.vendoo.co/app/item/abc123",
            vendoo_item_id="abc123",
        )
        self.db.add(self.job)
        self.db.commit()
        self.leftover = FillLogService(self.db).save_step(self.job, "filling_ebay", {
            "marketplace": "ebay",
            "entries": [
                {"field": "Occasion", "status": "skipped", "reason": "No value in listing", "selector": "#occasion"},
                {"field": "Title", "status": "filled", "selector": "#title", "value_preview": "Nike tee"},
            ],
        })[0]

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    @patch("vendoo_studio.routes.extension.dispatch_fill_fields", new_callable=AsyncMock)
    @patch("vendoo_studio.routes.extension.extension_manager")
    def test_fill_fields_sends_exact_selectors(self, manager, dispatch):
        manager.connected = True
        dispatch.return_value = True

        response = self.client.post(
            f"/api/jobs/{self.job.id}/fill-fields",
            json={"fields": [{"id": self.leftover.id, "value": "Casual"}]},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "dispatched")
        self.assertEqual(response.json()["current_step"], "filling_fields")
        dispatch.assert_awaited()
        sent_fields = dispatch.await_args.args[1]
        self.assertEqual(sent_fields, [{
            "id": self.leftover.id,
            "marketplace": "ebay",
            "field": "Occasion",
            "selector": "#occasion",
            "value": "Casual",
        }])
        self.db.refresh(self.job)
        self.assertEqual(self.job.listing_snapshot["ebay_specifics"]["Occasion"], "Casual")

    @patch("vendoo_studio.routes.extension.dispatch_fill_fields", new_callable=AsyncMock)
    @patch("vendoo_studio.routes.extension.extension_manager")
    def test_fill_fields_rejects_already_filled(self, manager, dispatch):
        manager.connected = True
        filled = self.db.query(FillLogEntry).filter(FillLogEntry.field == "Title").one()
        response = self.client.post(
            f"/api/jobs/{self.job.id}/fill-fields",
            json={"fields": [{"id": filled.id, "value": "Other"}]},
        )
        self.assertEqual(response.status_code, 400)
        dispatch.assert_not_awaited()

    @patch("vendoo_studio.routes.extension.extension_manager")
    def test_fill_fields_requires_connected_chrome(self, manager):
        manager.connected = False
        response = self.client.post(
            f"/api/jobs/{self.job.id}/fill-fields",
            json={"fields": [{"id": self.leftover.id, "value": "Casual"}]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Chrome is not connected", response.json()["detail"])

    def test_fill_fields_job_not_found(self):
        response = self.client.post(
            "/api/jobs/missing/fill-fields",
            json={"fields": [{"id": "x", "value": "Casual"}]},
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
