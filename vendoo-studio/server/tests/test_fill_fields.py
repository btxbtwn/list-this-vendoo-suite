from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.models.conversation import Conversation, Photo
from vendoo_studio.models.fill_log import FillLogEntry
from vendoo_studio.models.job import Job
from vendoo_studio.models.listing import Listing, ListingRevision  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ListingRepo
from vendoo_studio.services.fill_log import FillLogService


RETRY_LISTING = {
    "title": "Nike M Graphic T-Shirt Maroon Crewneck",
    "description": (
        "Nike graphic tee in maroon.\n\n"
        "Size: M\n"
        "Condition: Pre-Owned - Good; no major flaws visible in photos.\n"
        "Measurements: Pit to pit: 22\"; Length: 28\"; Sleeve: 8\"\n\n"
        "OFFERS WELCOME! Ships in 1-2 business days."
    ),
    "price": 24,
    "brand": "Nike",
    "size": "M",
    "sku": "NIKE-M-1",
    "weight_lb": 0,
    "weight_oz": 8,
    "package_dimensions_in": "13x10x3",
    "department": "Men",
    "condition": "Pre-Owned - Good",
    "ebay_specifics": {
        "type": "T-Shirt",
        "department": "Men",
        "sizeType": "Regular",
        "size": "M",
        "brand": "Nike",
    },
    "depop_specifics": {
        "source": "Preloved",
        "age": "Modern",
        "style": ["Casual"],
        "parcelSize": "Medium",
    },
}


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
        self.db.add(Photo(
            conversation_id=self.conv.id,
            original_filename="a.jpg",
            stored_filename="a.jpg",
            mime_type="image/jpeg",
            size_bytes=10,
            display_order=0,
        ))
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
        latest = ListingRepo(self.db).get_revisions(self.conv.id)[0]
        self.assertEqual(latest.listing_json["ebay_specifics"]["occasion"], "Casual")

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

    @patch("vendoo_studio.routes.extension.dispatch_fill_fields", new_callable=AsyncMock)
    @patch("vendoo_studio.routes.extension.extension_manager")
    def test_fill_fields_dispatch_failure_releases_active_job(self, manager, dispatch):
        manager.connected = True
        dispatch.return_value = False

        response = self.client.post(
            f"/api/jobs/{self.job.id}/fill-fields",
            json={"fields": [{"id": self.leftover.id, "value": "Casual"}]},
        )

        self.assertEqual(response.status_code, 503)
        self.db.refresh(self.job)
        self.assertEqual(self.job.status, "failed")
        self.assertEqual(self.job.current_step, "filling_fields")

    def test_generic_retry_does_not_restart_a_leftover_fill_as_a_full_job(self):
        self.job.status = "failed"
        self.job.current_step = "filling_fields"
        self.db.commit()

        response = self.client.post(f"/api/jobs/{self.job.id}/retry")

        self.assertEqual(response.status_code, 400)
        self.assertIn("from Fields", response.json()["detail"])

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
        latest = ListingRepo(self.db).get_revisions(self.conv.id)[0]
        self.assertEqual(latest.listing_json["sku"], "ABC-1")

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

    @patch("vendoo_studio.routes.extension.dispatch_fill_fields", new_callable=AsyncMock)
    @patch("vendoo_studio.routes.extension.extension_manager")
    def test_fill_fields_allows_long_description(self, manager, dispatch):
        manager.connected = True
        dispatch.return_value = True
        description = "A" * 600
        leftovers = FillLogService(self.db).save_step(self.job, "filling_fields", {
            "marketplace": "etsy",
            "entries": [
                {"field": "Description", "status": "new", "marketplace": "etsy", "selector": "#description"},
            ],
        })

        response = self.client.post(
            f"/api/jobs/{self.job.id}/fill-fields",
            json={"fields": [{"id": leftovers[0].id, "value": description}]},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(dispatch.await_args.args[1][0]["value"], description)

    @patch("vendoo_studio.routes.extension.extension_manager")
    def test_fill_fields_rejects_oversized_value(self, manager):
        manager.connected = True
        leftovers = FillLogService(self.db).save_step(self.job, "filling_fields", {
            "marketplace": "etsy",
            "entries": [
                {"field": "Description", "status": "new", "marketplace": "etsy", "selector": "#description"},
            ],
        })

        response = self.client.post(
            f"/api/jobs/{self.job.id}/fill-fields",
            json={"fields": [{"id": leftovers[0].id, "value": "A" * 10_001}]},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("too long", response.json()["detail"])

    @patch("vendoo_studio.routes.extension.dispatch_queued_jobs", new_callable=AsyncMock)
    def test_retry_preserves_approved_snapshot(self, dispatch):
        from vendoo_studio.services.registry import MEN_TSHIRT_PATH, WOMEN_TOPS_PATH

        ListingRepo(self.db).save_revision(self.conv.id, {
            **RETRY_LISTING,
            "department": "Men",
            "category_path": MEN_TSHIRT_PATH,
            "ebay_specifics": {
                **RETRY_LISTING["ebay_specifics"],
                "department": "Men",
                "type": "T-Shirt",
            },
        }, source="model_refinement")
        self.job.listing_snapshot = {
            **RETRY_LISTING,
            "department": "Women",
            "category_path": WOMEN_TOPS_PATH,
            "ebay_specifics": {
                **RETRY_LISTING["ebay_specifics"],
                "department": "Women",
                "type": "T-Shirt",
            },
        }
        self.job.status = "completed"
        self.db.commit()

        response = self.client.post(f"/api/jobs/{self.job.id}/retry")

        self.assertEqual(response.status_code, 200, response.text)
        self.db.refresh(self.job)
        self.assertEqual(self.job.listing_snapshot["category_path"], WOMEN_TOPS_PATH)
        self.assertEqual(self.job.listing_snapshot["department"], "Women")
        self.assertEqual(self.job.listing_snapshot["ebay_specifics"]["department"], "Women")
        dispatch.assert_awaited()

    @patch("vendoo_studio.routes.extension.dispatch_queued_jobs", new_callable=AsyncMock)
    def test_failed_retry_resumes_and_keeps_earlier_fill_logs(self, dispatch):
        from vendoo_studio.repositories.queries import JobRepo

        ListingRepo(self.db).save_revision(self.conv.id, RETRY_LISTING, source="user_form")
        FillLogService(self.db).save_step(self.job, "filling_general", {
            "marketplace": "general",
            "entries": [
                {"field": "Title", "status": "filled", "selector": "#title", "value_preview": "Nike tee"},
            ],
        })
        FillLogService(self.db).save_step(self.job, "filling_etsy", {
            "marketplace": "etsy",
            "entries": [
                {"field": "Who Made", "status": "failed", "selector": "#whoMade", "value_preview": "Someone else"},
            ],
        })
        self.job.status = "failed"
        self.job.current_step = "filling_etsy"
        self.job.last_error = "FILL_MARKETPLACE timed out after 90s"
        self.job.listing_snapshot = RETRY_LISTING
        self.db.commit()

        response = self.client.post(f"/api/jobs/{self.job.id}/retry")

        self.assertEqual(response.status_code, 200, response.text)
        self.db.refresh(self.job)
        self.assertEqual(self.job.status, "queued")
        report = FillLogService(self.db).report_for_job(self.job)
        self.assertNotIn("etsy", report["by_marketplace"])
        self.assertIn("general", report["by_marketplace"])
        self.assertIn("ebay", report["by_marketplace"])
        self.assertEqual(report["by_marketplace"]["general"]["summary"]["filled"], 1)
        event = JobRepo(self.db).latest_event(self.job.id, "retried")
        self.assertIsNotNone(event)
        self.assertEqual(event.payload.get("resume_from"), "filling_etsy")
        dispatch.assert_awaited()


if __name__ == "__main__":
    unittest.main()
