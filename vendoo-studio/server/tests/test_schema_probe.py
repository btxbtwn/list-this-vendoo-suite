from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vendoo_studio.database import Base
from vendoo_studio.models.conversation import Conversation
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.job import Job  # noqa: F401
from vendoo_studio.models.listing import Listing, ListingRevision  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import JobRepo, ListingRepo
from vendoo_studio.services.schema_probe import (
    SCHEMA_PROBE_FLAG,
    is_schema_probe_job,
    listing_for_extension,
    maybe_start_schema_probe,
    should_probe,
)

EXTENSION_DIR = Path(__file__).resolve().parents[3] / "vendoo-extension"
MEN_PATH = "Clothing, Shoes & Accessories > Men > Men's Clothing > Shirts > T-Shirts"


class SchemaProbeHelpersTest(unittest.TestCase):
    def test_should_probe_requires_leaf_path(self):
        self.assertFalse(should_probe({}))
        self.assertFalse(should_probe({"category_path": "Tops"}))
        self.assertTrue(should_probe({"category_path": MEN_PATH}))
        self.assertFalse(should_probe({"category_path": MEN_PATH}, previous_path=MEN_PATH))

    def test_listing_for_extension_strips_studio_keys(self):
        cleaned = listing_for_extension({
            "title": "Tee",
            "category_path": MEN_PATH,
            "platforms": ["ebay"],
            SCHEMA_PROBE_FLAG: True,
            "_other": 1,
        })
        self.assertEqual(cleaned["title"], "Tee")
        self.assertNotIn(SCHEMA_PROBE_FLAG, cleaned)
        self.assertNotIn("_other", cleaned)
        self.assertNotIn("platforms", cleaned)

    def test_seed_probe_general_fields_from_notes_and_defaults(self):
        from vendoo_studio.services.schema_probe import seed_probe_general_fields

        seeded = seed_probe_general_fields({"category_path": MEN_PATH}, '{"condition":"Good"}')
        self.assertEqual(seeded["condition"], "Good")
        self.assertEqual(seeded["title"], "Draft listing")
        self.assertEqual(seeded["zipCode"], "70125")
        self.assertEqual(seeded["quantity"], 1)

        kept = seed_probe_general_fields({
            "title": "Kept",
            "condition": "New With Tags/Box",
            "zipCode": "10001",
            "quantity": 2,
        }, '{"condition":"Good"}')
        self.assertEqual(kept["title"], "Kept")
        self.assertEqual(kept["condition"], "New With Tags/Box")
        self.assertEqual(kept["zipCode"], "10001")
        self.assertEqual(kept["quantity"], 2)


class SchemaProbeServiceTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.conv = Conversation(title="Probe listing")
        self.db.add(self.conv)
        self.db.commit()
        ListingRepo(self.db).save_revision(self.conv.id, {
            "title": "Nike tee",
            "category_path": MEN_PATH,
            "ebay_specifics": {},
        }, source="model")
        self.tmp = tempfile.TemporaryDirectory()
        import vendoo_studio.services.fill_log as fill_log_mod
        self._orig_dir = fill_log_mod.FILL_LOGS_DIR
        fill_log_mod.FILL_LOGS_DIR = self.tmp.name

    def tearDown(self):
        import vendoo_studio.services.fill_log as fill_log_mod
        fill_log_mod.FILL_LOGS_DIR = self._orig_dir
        self.db.close()
        self.tmp.cleanup()

    def test_maybe_start_creates_schema_probe_job_without_photos(self):
        result = maybe_start_schema_probe(
            self.db,
            self.conv.id,
            listing={"title": "Nike tee", "category_path": MEN_PATH},
            reason="generate",
        )
        self.assertTrue(result["started"])
        job = JobRepo(self.db).get(result["job_id"])
        self.assertTrue(is_schema_probe_job(job))
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.listing_snapshot.get("category_path"), MEN_PATH)
        self.assertTrue(job.listing_snapshot.get(SCHEMA_PROBE_FLAG))
        self.assertIsInstance(job.listing_snapshot.get("platforms"), list)

    def test_retry_reuses_draft_created_by_failed_probe(self):
        first = maybe_start_schema_probe(self.db, self.conv.id)
        prior = JobRepo(self.db).get(first["job_id"])
        prior.status = "failed"
        prior.vendoo_item_id = "saved-probe-draft"
        prior.vendoo_url = "https://web.vendoo.co/app/item/saved-probe-draft"
        self.db.commit()
        result = maybe_start_schema_probe(self.db, self.conv.id)
        self.assertTrue(result["started"])
        retry = JobRepo(self.db).get(result["job_id"])
        self.assertEqual(retry.vendoo_item_id, prior.vendoo_item_id)
        self.assertEqual(retry.vendoo_url, prior.vendoo_url)

    def test_maybe_start_skips_when_another_job_active(self):
        JobRepo(self.db).create(
            conv_id=self.conv.id,
            approved_revision_id="rev1",
            listing_snapshot={"title": "Other", "category_path": MEN_PATH},
            status="dispatched",
            current_step="filling_general",
        )
        result = maybe_start_schema_probe(
            self.db,
            self.conv.id,
            listing={"title": "Nike tee", "category_path": MEN_PATH},
        )
        self.assertFalse(result["started"])
        self.assertEqual(result["reason"], "busy")

    def test_maybe_start_skips_duplicate_completed_probe(self):
        first = maybe_start_schema_probe(
            self.db,
            self.conv.id,
            listing={"title": "Nike tee", "category_path": MEN_PATH},
        )
        job = JobRepo(self.db).get(first["job_id"])
        job.status = "completed"
        job.current_step = "schema_probe_done"
        self.db.commit()

        second = maybe_start_schema_probe(
            self.db,
            self.conv.id,
            listing={"title": "Nike tee", "category_path": MEN_PATH},
        )
        self.assertFalse(second["started"])
        self.assertEqual(second["reason"], "already_done")


class SchemaProbeExtensionTest(unittest.TestCase):
    def test_schema_probe_job_steps_skip_marketplace_fill(self):
        text = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
        start = text.index("function buildJobSteps(job)")
        end = text.index("const NEW_ITEM_URL")
        preamble = """
const openVendooListing = async () => ({ ok: true });
const waitForContentScript = async () => ({ ok: true });
const uploadPhotos = async () => ({ ok: true });
const clearGeneral = async () => ({ ok: true });
const fillGeneral = async () => ({ ok: true });
const selectGeneralCategoryOnly = async () => ({ ok: true });
const saveGeneral = async () => ({ ok: true });
const auditGeneral = async () => ({ ok: true });
const checkDraftSafety = async () => ({ ok: true });
const discoverSchema = async () => ({ ok: true });
const clearMarketplace = async () => ({ ok: true });
const fillMarketplace = async () => ({ ok: true });
const saveMarketplace = async () => ({ ok: true });
const saveMarketplaces = async () => ({ ok: true });
const auditMarketplace = async () => ({ ok: true });
const auditAllMarketplaces = async () => ({ ok: true });
"""
        script = text[start:end] + """
const probe = buildJobSteps({
  options: { mode: 'schema_probe', platforms: ['ebay', 'poshmark'], skipPhotos: true },
}).map((step) => step.step);
const probeUpdate = buildJobSteps({
  options: { mode: 'schema_probe', platforms: ['ebay'], reuseExistingItem: true, skipPhotos: true },
}).map((step) => step.step);
const fill = buildJobSteps({
  options: { platforms: ['ebay'], clearBeforeFill: false, skipPhotos: true },
}).map((step) => step.step);
const update = buildJobSteps({
  options: { platforms: ['ebay'], reuseExistingItem: true, skipPhotos: false },
}).map((step) => step.step);
const cached = buildJobSteps({
  options: { platforms: ['ebay'], skipPhotos: true, skipDiscoverSchema: true },
}).map((step) => step.step);
const auditOnly = buildJobSteps({
  options: { platforms: ['ebay'], resumeFrom: 'auditing_ebay', reuseExistingItem: true },
}).map((step) => step.step);
console.log(JSON.stringify({ probe, probeUpdate, fill, update, cached, auditOnly }));
"""
        proc = subprocess.run(
            ["node", "-e", preamble + script],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(proc.stdout)
        self.assertEqual(
            result["probe"],
            ["opening_vendoo", "waiting_ready", "selecting_category", "saving_general", "discovering_schema"],
        )
        self.assertNotIn("filling_ebay", result["probe"])
        self.assertLess(
            result["probeUpdate"].index("checking_draft_safety"),
            result["probeUpdate"].index("saving_general"),
        )
        self.assertIn("filling_ebay", result["fill"])
        self.assertIn("discovering_schema", result["fill"])
        self.assertIn("saving_marketplaces", result["fill"])
        self.assertNotIn("saving_ebay", result["fill"])
        self.assertNotIn("auditing_ebay", result["fill"])
        self.assertLess(result["update"].index("checking_draft_safety"), result["update"].index("uploading_photos"))
        self.assertNotIn("discovering_schema", result["cached"])
        self.assertEqual(
            result["auditOnly"],
            ["opening_vendoo", "waiting_ready", "checking_draft_safety", "auditing_ebay"],
        )

    def test_content_script_has_set_general_category(self):
        content = (EXTENSION_DIR / "content-scripts" / "vendoo.js").read_text(encoding="utf-8")
        self.assertIn("async function setGeneralCategoryOnly", content)
        self.assertIn("SET_GENERAL_CATEGORY", content)
        self.assertIn("Draft listing", content)
        self.assertIn("Vendoo keeps Save disabled", content)
        self.assertIn("String(data.condition || '').trim() || 'Good'", content)
        self.assertIn("await fillTextField(VENDOO_SELECTORS.quantity, quantity, 'Quantity')", content)


class SchemaProbeDispatchTest(unittest.TestCase):
    def test_dispatch_sets_schema_probe_mode(self):
        from vendoo_studio.routes import extension as extension_routes

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        conv = Conversation(title="Probe")
        db.add(conv)
        db.commit()
        job = JobRepo(db).create(
            conv_id=conv.id,
            approved_revision_id="rev1",
            listing_snapshot={
                "title": "Tee",
                "category_path": MEN_PATH,
                "platforms": ["ebay", "poshmark"],
                SCHEMA_PROBE_FLAG: True,
            },
        )

        captured = {}

        class FakeManager:
            connected = True
            paired = True

            async def send_message(self, message):
                captured["message"] = message
                return True

        async def run():
            with patch.object(extension_routes, "SessionLocal", return_value=db), \
                 patch.object(extension_routes, "extension_manager", FakeManager()):
                await extension_routes.dispatch_queued_jobs()

        import asyncio
        asyncio.run(run())
        payload = captured["message"]["payload"]
        self.assertEqual(payload["options"]["mode"], "schema_probe")
        self.assertTrue(payload["options"]["skipPhotos"])
        self.assertEqual(payload["options"]["platforms"], ["ebay", "poshmark"])
        self.assertNotIn(SCHEMA_PROBE_FLAG, payload["listing"])
        self.assertEqual(payload["listing"]["category_path"], MEN_PATH)
        db.close()


if __name__ == "__main__":
    unittest.main()
