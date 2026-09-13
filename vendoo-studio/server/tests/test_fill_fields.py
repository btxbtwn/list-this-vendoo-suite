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
from vendoo_studio.repositories.queries import ListingRepo
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

    @patch("vendoo_studio.routes.extension.dispatch_fill_fields", new_callable=AsyncMock)
    @patch("vendoo_studio.routes.extension.extension_manager")
    def test_fill_named_field_from_listing_revision(self, manager, dispatch):
        manager.connected = True
        dispatch.return_value = True
        ListingRepo(self.db).save_revision(
            self.conv.id,
            {"title": "Nike tee", "sku": "ABC-1", "ebay_specifics": {}},
            source="model_refinement",
        )

        response = self.client.post(
            f"/api/jobs/{self.job.id}/fill-fields",
            json={"fields": [{"marketplace": "general", "field": "SKU"}]},
        )

        self.assertEqual(response.status_code, 200, response.text)
        sent_fields = dispatch.await_args.args[1]
        self.assertEqual(sent_fields[0]["marketplace"], "general")
        self.assertEqual(sent_fields[0]["field"], "SKU")
        self.assertEqual(sent_fields[0]["value"], "ABC-1")
        self.db.refresh(self.job)
        self.assertEqual(self.job.listing_snapshot["sku"], "ABC-1")

    @patch("vendoo_studio.routes.extension.extension_manager")
    def test_fill_named_field_requires_value(self, manager):
        manager.connected = True
        response = self.client.post(
            f"/api/jobs/{self.job.id}/fill-fields",
            json={"fields": [{"marketplace": "general", "field": "SKU"}]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Ask chat", response.json()["detail"])

    @patch("vendoo_studio.routes.extension.dispatch_fill_fields", new_callable=AsyncMock)
    @patch("vendoo_studio.routes.extension.extension_manager")
    def test_fill_fields_resolves_marketplace_values_from_listing(self, manager, dispatch):
        manager.connected = True
        dispatch.return_value = True
        ListingRepo(self.db).save_revision(
            self.conv.id,
            {
                "title": "Nike tee",
                "size": "S",
                "ebay_specifics": {
                    "department": "Women",
                    "type": "Blouse",
                    "countryOfOrigin": "United States",
                },
                "etsy_specifics": {"when_made": "2010s"},
            },
            source="model_refinement",
        )
        leftovers = FillLogService(self.db).save_step(self.job, "filling_fields", {
            "marketplace": "ebay",
            "entries": [
                {"field": "Size", "status": "new", "marketplace": "poshmark", "selector": "#posh-size"},
                {"field": "When Was It Made?", "status": "new", "marketplace": "etsy", "selector": "#whenMade"},
                {"field": "Department", "status": "new", "marketplace": "ebay", "selector": "#department"},
                {"field": "Type", "status": "new", "marketplace": "ebay", "selector": "#type"},
                {"field": "Country of Origin", "status": "new", "marketplace": "ebay", "selector": "#origin"},
            ],
        })

        response = self.client.post(
            f"/api/jobs/{self.job.id}/fill-fields",
            json={"fields": [{"id": entry.id} for entry in leftovers]},
        )

        self.assertEqual(response.status_code, 200, response.text)
        sent = {item["field"]: item["value"] for item in dispatch.await_args.args[1]}
        self.assertEqual(sent["Size"], "S")
        self.assertEqual(sent["When Was It Made?"], "2010s")
        self.assertEqual(sent["Department"], "Women")
        self.assertEqual(sent["Type"], "Blouse")
        self.assertEqual(sent["Country of Origin"], "United States")

    @patch("vendoo_studio.routes.extension.dispatch_queued_jobs", new_callable=AsyncMock)
    def test_retry_refreshes_snapshot_from_latest_listing(self, dispatch):
        from vendoo_studio.services.registry import MEN_TSHIRT_PATH, WOMEN_TOPS_PATH

        ListingRepo(self.db).save_revision(self.conv.id, {
            "title": "Casa San Bord M Graphic T-Shirt Maroon Crewneck Cotton",
            "department": "Men",
            "category_path": MEN_TSHIRT_PATH,
            "condition": "Good",
            "ebay_specifics": {"department": "Men", "type": "T-Shirt"},
        }, source="model_refinement")
        self.job.listing_snapshot = {
            "title": "Casa San Bord M Graphic T-Shirt Maroon Crewneck Cotton",
            "category_path": WOMEN_TOPS_PATH,
            "ebay_specifics": {"department": "Women", "type": "T-Shirt"},
        }
        self.job.status = "completed"
        self.db.commit()

        response = self.client.post(f"/api/jobs/{self.job.id}/retry")

        self.assertEqual(response.status_code, 200, response.text)
        self.db.refresh(self.job)
        self.assertEqual(self.job.listing_snapshot["category_path"], MEN_TSHIRT_PATH)
        self.assertEqual(self.job.listing_snapshot["department"], "Men")
        self.assertEqual(self.job.listing_snapshot["ebay_specifics"]["department"], "Men")
        dispatch.assert_awaited()


if __name__ == "__main__":
    unittest.main()
