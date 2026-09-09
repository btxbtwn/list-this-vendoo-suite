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
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.services.fill_log import (
    FillLogService,
    preview_value,
    sanitize_entries,
    summarize,
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


class FillLogRouteTest(unittest.TestCase):
    def test_fill_log_route_returns_job_not_found(self):
        from fastapi.testclient import TestClient
        from vendoo_studio.main import app

        client = TestClient(app)
        response = client.get("/api/jobs/missing/fill-log")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Job not found")


if __name__ == "__main__":
    unittest.main()
