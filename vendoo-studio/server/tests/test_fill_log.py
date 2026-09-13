from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vendoo_studio.database import Base
from vendoo_studio.models.conversation import Conversation
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.job import Job
from vendoo_studio.models.listing import Listing, ListingRevision  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.services.fill_log import (
    FillLogService,
    extract_missing_fields,
    listing_value_for_field,
    preview_value,
    sanitize_entries,
    summarize,
    write_values_into_listing,
)


class FillLogHelpersTest(unittest.TestCase):
    def test_preview_truncates_and_collapses_whitespace(self):
        self.assertEqual(preview_value("  Nike   tee  "), "Nike tee")
        long = "x" * 90
        self.assertEqual(preview_value(long), ("x" * 77) + "...")

    def test_sanitize_drops_unknown_statuses_and_caps_preview(self):
        entries = sanitize_entries({
            "marketplace": "general",
            "entries": [
                {"field": "Title", "status": "filled", "value_preview": "Nike tee"},
                {"field": "Size", "status": "not_found", "reason": "Element not found"},
                {"field": "Occasion", "status": "new", "selector": "#occasion"},
                {"field": "Hack", "status": "drop_table"},
                {"field": "", "status": "filled"},
            ],
        })
        self.assertEqual([e["field"] for e in entries], ["Title", "Size", "Occasion"])
        counts = summarize(entries)
        self.assertEqual(counts["filled"], 1)
        self.assertEqual(counts["not_found"], 1)
        self.assertEqual(counts["new"], 1)
        self.assertEqual(counts["failed"], 0)

    def test_extract_missing_fields_from_fenced_json(self):
        fields = extract_missing_fields(
            'Here you go:\n```json\n{"missing_fields":[{"marketplace":"general","field":"SKU","value":"ABC-1"}]}\n```'
        )
        self.assertEqual(fields, [{"marketplace": "general", "field": "SKU", "value": "ABC-1"}])

    def test_extract_missing_fields_ignores_json_patch(self):
        self.assertIsNone(extract_missing_fields('[{"op":"replace","path":"/sku","value":"ABC-1"}]'))

    def test_listing_value_for_field_maps_leftover_labels(self):
        listing = {
            "size": "S",
            "department": "Women",
            "ebay_specifics": {
                "department": "Women",
                "type": "Blouse",
                "countryOfOrigin": "United States",
                "yearManufactured": "2010s",
            },
            "etsy_specifics": {"when_made": "2010 - 2019 (Recently)"},
        }
        self.assertEqual(listing_value_for_field(listing, "poshmark", "Size"), "S")
        self.assertEqual(listing_value_for_field(listing, "etsy", "When Was It Made?"), "2010 - 2019 (Recently)")
        self.assertEqual(listing_value_for_field(listing, "ebay", "Department"), "Women")
        self.assertEqual(listing_value_for_field(listing, "ebay", "Type"), "Blouse")
        self.assertEqual(listing_value_for_field(listing, "ebay", "Country of Origin"), "United States")

    def test_listing_value_for_field_maps_poshmark_category(self):
        listing = {
            "title": "Amplife L Graphic T-Shirt Black Cotton",
            "category_path": "Clothing, Shoes & Accessories > Men > Men's Clothing > Shirts > T-Shirts",
            "ebay_specifics": {"department": "Men", "type": "T-Shirt", "sleeveLength": "Short Sleeve"},
        }
        self.assertEqual(
            listing_value_for_field(listing, "poshmark", "Category"),
            "Men > Shirts > Tees - Short Sleeve",
        )

    def test_listing_value_for_field_uses_ebay_year_for_etsy_when_made(self):
        listing = {
            "ebay_specifics": {"yearManufactured": "2014"},
            "etsy_specifics": {},
        }
        self.assertEqual(listing_value_for_field(listing, "etsy", "When Made"), "2014")

    def test_listing_value_for_field_reads_etsy_category_specifics(self):
        listing = {
            "size": "XL",
            "etsy_specifics": {
                "materials": ["Cotton"],
                "category_specifics": {
                    "graphic": "Sports & fitness",
                    "fabricPattern": "Solid",
                },
            },
        }
        self.assertEqual(listing_value_for_field(listing, "etsy", "Graphic"), "Sports & fitness")
        self.assertEqual(listing_value_for_field(listing, "etsy", "Fabric pattern"), "Solid")
        self.assertEqual(listing_value_for_field(listing, "etsy", "Materials"), "Cotton")
        self.assertEqual(listing_value_for_field(listing, "etsy", "Size"), "XL")


class FillLogServiceTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.conv = Conversation(title="Nike tee")
        self.db.add(self.conv)
        self.db.commit()
        self.job = Job(
            conversation_id=self.conv.id,
            approved_revision_id="rev1",
            listing_snapshot={"title": "Nike tee", "category_path": "Tops"},
        )
        self.db.add(self.job)
        self.db.commit()
        self.tmp = tempfile.TemporaryDirectory()
        import vendoo_studio.services.fill_log as fill_log_mod
        self._orig_dir = fill_log_mod.FILL_LOGS_DIR
        fill_log_mod.FILL_LOGS_DIR = self.tmp.name

    def tearDown(self):
        import vendoo_studio.services.fill_log as fill_log_mod
        fill_log_mod.FILL_LOGS_DIR = self._orig_dir
        self.db.close()
        self.tmp.cleanup()

    def test_save_step_persists_markdown_and_new_registry_fields(self):
        service = FillLogService(self.db)
        service.save_step(self.job, "filling_general", {
            "marketplace": "general",
            "entries": [
                {"field": "Title", "status": "filled", "selector": "#generalDetails.title", "value_preview": "Nike tee"},
                {"field": "Size", "status": "not_found", "reason": "Element not found", "selector": "#generalDetails.size"},
                {"field": "Occasion", "status": "new", "reason": "Visible on form, not filled by automation", "selector": "#occasion"},
            ],
        })

        report = service.report_for_job(self.job)
        self.assertEqual(report["summary"]["filled"], 1)
        self.assertEqual(report["summary"]["not_found"], 1)
        self.assertEqual(report["summary"]["new"], 1)
        self.assertIn("general", report["by_marketplace"])
        markdown = Path(self.tmp.name).joinpath(f"{self.job.id}.md").read_text()
        self.assertIn("New fields on the form", markdown)
        self.assertIn("Did not work — field missing", markdown)

        occasion = self.db.query(FieldRegistry).filter(FieldRegistry.normalized_label == "occasion").one()
        self.assertEqual(occasion.marketplace, "general")
        size = self.db.query(FieldRegistry).filter(FieldRegistry.normalized_label == "size").one()
        self.assertEqual(size.known_selectors[0]["failure_count"], 1)

    def test_save_step_backfills_learned_listing_fields(self):
        from vendoo_studio.repositories.queries import ListingRepo

        listing_repo = ListingRepo(self.db)
        listing_repo.save_revision(self.conv.id, {
            "title": "Nike tee",
            "category_path": "Tops",
            "size": "S",
            "ebay_specifics": {"type": "T-Shirt"},
        }, source="model")

        service = FillLogService(self.db)
        service.save_step(self.job, "filling_ebay", {
            "marketplace": "ebay",
            "entries": [
                {"field": "Character", "status": "new", "selector": "#character"},
                {"field": "Allow Best Offer", "status": "new", "selector": "#best-offer"},
                {"field": "Size", "status": "new", "selector": "#size"},
            ],
        })

        listing = listing_repo.get_revisions(self.conv.id)[0].listing_json
        self.assertEqual(listing["ebay_specifics"]["type"], "T-Shirt")
        self.assertEqual(listing["ebay_specifics"]["character"], "")
        self.assertNotIn("allowBestOffer", listing["ebay_specifics"])
        self.assertNotIn("size", listing["ebay_specifics"])
        self.assertEqual(
            self.db.query(FieldRegistry).filter(FieldRegistry.normalized_label == "character").one().marketplace,
            "ebay",
        )

    def test_retry_clears_previous_log(self):
        service = FillLogService(self.db)
        service.save_step(self.job, "filling_general", {
            "marketplace": "general",
            "entries": [{"field": "Title", "status": "filled", "value_preview": "old"}],
        })
        service.clear_job(self.job.id)
        report = service.report_for_job(self.job)
        self.assertEqual(sum(report["summary"].values()), 0)
        self.assertFalse(Path(self.tmp.name).joinpath(f"{self.job.id}.md").exists())

    def test_write_values_into_listing_maps_general_and_specifics(self):
        listing = write_values_into_listing(
            {"title": "Old", "ebay_specifics": {"Season": "Fall"}},
            [
                {"marketplace": "general", "field": "Title", "value": "Nike tee"},
                {"marketplace": "general", "field": "Quantity", "value": "2"},
                {"marketplace": "ebay", "field": "Occasion", "value": "Casual"},
                {"marketplace": "ebay", "field": "eBay Season", "value": "Summer"},
            ],
        )
        self.assertEqual(listing["title"], "Nike tee")
        self.assertEqual(listing["quantity"], 2)
        self.assertEqual(listing["ebay_specifics"]["Occasion"], "Casual")
        self.assertEqual(listing["ebay_specifics"]["Season"], "Summer")

    def test_apply_field_results_updates_existing_rows_by_id(self):
        service = FillLogService(self.db)
        saved = service.save_step(self.job, "filling_ebay", {
            "marketplace": "ebay",
            "entries": [
                {"field": "Occasion", "status": "skipped", "reason": "No value in listing", "selector": "#occasion"},
                {"field": "Title", "status": "filled", "selector": "#title", "value_preview": "Nike tee"},
            ],
        })
        leftover = next(entry for entry in saved if entry.field == "Occasion")
        updated = service.apply_field_results(self.job, {
            "entries": [
                {"id": leftover.id, "marketplace": "ebay", "field": "Occasion", "status": "filled", "selector": "#occasion", "value": "Casual"},
            ],
        })
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0].status, "filled")
        self.assertEqual(updated[0].value_preview, "Casual")
        report = service.report_for_job(self.job)
        self.assertEqual(report["summary"]["filled"], 2)
        self.assertEqual(report["summary"]["skipped"], 0)


class FillLogRouteTest(unittest.TestCase):
    def test_fill_log_route_returns_job_not_found(self):
        from fastapi.testclient import TestClient
        from vendoo_studio.database import init_db
        from vendoo_studio.main import app

        init_db()
        client = TestClient(app)
        with client:
            response = client.get("/api/jobs/missing/fill-log")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Job not found")


if __name__ == "__main__":
    unittest.main()
