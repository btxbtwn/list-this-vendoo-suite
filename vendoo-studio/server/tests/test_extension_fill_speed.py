from __future__ import annotations

import json
import subprocess
import unittest
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vendoo_studio.database import Base
from vendoo_studio.models.catalog import CategorySchema  # noqa: F401
from vendoo_studio.models.conversation import utcnow
from vendoo_studio.models.fill_log import FillLogEntry
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services.job_metrics import fill_success_stats, job_timing
from vendoo_studio.services.send_skip import matching_marketplaces, specifics_match
from extension_sources import background_source

EXTENSION = Path(__file__).resolve().parents[3] / "vendoo-extension"


def _node(script: str) -> dict:
    return json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)


class _DbTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.conv = ConversationRepo(self.db).create(title="Tee")
        revision = ListingRepo(self.db).save_revision(self.conv.id, {"title": "Tee"}, source="model")
        self.job = JobRepo(self.db).create(
            conv_id=self.conv.id, approved_revision_id=revision.id,
            listing_snapshot={"title": "Tee"}, status="completed", vendoo_item_id="item-1",
        )


class SendSkipTest(_DbTest):
    ITEM = {
        "itemID": "item-1",
        "generalDetails": {"title": "Tee"},
        "listings": {
            "ebay": {"marketplaceSpecifics": {"type": "T-Shirt", "department": "Men"},
                     "categorySpecifics": {"material": "Cotton"}},
            "depop": {"marketplaceSpecifics": {"source": "Preloved", "style": ["Streetwear", "Vintage"]}},
        },
    }

    def test_specifics_match_normalizes_case_numbers_and_lists(self):
        self.assertTrue(specifics_match({"type": "t-shirt", "price": 20}, {"type": "T-Shirt", "price": "20.0"}))
        self.assertTrue(specifics_match({"style": ["vintage", "Streetwear"]}, {"style": ["Streetwear", "Vintage"]}))
        self.assertFalse(specifics_match({"type": "Tank"}, {"type": "T-Shirt"}))
        self.assertFalse(specifics_match({"type": "T-Shirt", "sleeve": "Short"}, {"type": "T-Shirt"}))
        self.assertFalse(specifics_match({}, {"type": "T-Shirt"}))

    def test_only_marketplaces_matching_the_latest_draft_are_skipped(self):
        JobRepo(self.db).save_vendoo_draft(self.job.id, item=self.ITEM, item_id="item-1", source="api_readback")
        listing = {
            "ebay_specifics": {"type": "T-Shirt", "department": "Men", "material": "cotton"},
            "depop_specifics": {"source": "Preloved", "style": ["Streetwear", "Y2K"]},
        }
        skip = matching_marketplaces(self.db, self.conv.id, "item-1", listing, ["ebay", "depop", "etsy"])
        self.assertEqual(skip, ["ebay"])
        self.assertEqual(matching_marketplaces(self.db, self.conv.id, "other-item", listing, ["ebay"]), [])


class JobMetricsTest(_DbTest):
    def test_job_timing_prefers_extension_durations(self):
        repo = JobRepo(self.db)
        repo.add_event(self.job.id, "step_completed", "filling_general", {"duration_ms": 4200})
        repo.add_event(self.job.id, "step_completed", "saving_ebay", {"duration_ms": 10, "skipped": True})
        repo.add_event(self.job.id, "step_failed", "filling_etsy", {"error": "x"})
        timing = job_timing(self.db, self.job.id)
        self.assertEqual([step["step"] for step in timing["steps"]], ["filling_general", "saving_ebay", "filling_etsy"])
        self.assertEqual(timing["steps"][0]["duration_ms"], 4200)
        self.assertTrue(timing["steps"][1]["skipped"])
        self.assertEqual(timing["steps"][2]["source"], "event_gap")
        self.assertEqual(timing["slowest"][0]["step"], "filling_general")

    def test_fill_stats_rank_worst_fields_first(self):
        now = utcnow()
        rows = [
            ("ebay", "Type", "filled"), ("ebay", "Type", "filled"),
            ("etsy", "Sleeve length", "invalid"), ("etsy", "Sleeve length", "filled"),
            ("etsy", "Holiday", "skipped"),
        ]
        for marketplace, field, status in rows:
            self.db.add(FillLogEntry(job_id=self.job.id, conversation_id=self.conv.id, step="filling_fields",
                                     marketplace=marketplace, field=field, status=status, created_at=now))
        self.db.add(FillLogEntry(job_id=self.job.id, conversation_id=self.conv.id, step="old",
                                 marketplace="ebay", field="Type", status="invalid",
                                 created_at=now - timedelta(days=90)))
        self.db.commit()
        stats = fill_success_stats(self.db, days=30)
        self.assertEqual(stats["entries"], 5)
        self.assertEqual(stats["fields"][0]["field"], "Sleeve length")
        self.assertEqual(stats["fields"][0]["success_rate"], 0.5)
        self.assertEqual(stats["by_marketplace"]["ebay"]["success_rate"], 1.0)


class ExtensionWaitTest(unittest.TestCase):
    def test_wait_until_returns_early_and_honors_ceiling(self):
        source = (EXTENSION / "content-scripts" / "vendoo.js").read_text()
        helpers = source[source.index("  const POLL_MS"):source.index("  function previewValue")]
        script = """
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let options = [];
const listOpenDropdownOptions = () => options;
""" + helpers + """
(async () => {
  let ready = false;
  setTimeout(() => { ready = true; }, 40);
  let start = Date.now();
  const early = await waitUntil(() => ready, 1000);
  const earlyMs = Date.now() - start;
  start = Date.now();
  const timeout = await waitUntil(() => false, 80);
  const timeoutMs = Date.now() - start;
  setTimeout(() => { options = [{text: 'Small'}, {text: 'Medium'}]; }, 30);
  start = Date.now();
  const settled = await waitForMenuSettled(() => null, 2000);
  const settledMs = Date.now() - start;
  console.log(JSON.stringify({early, earlyMs, timeout, timeoutMs, settled, settledMs}));
})();
"""
        result = _node(script)
        self.assertTrue(result["early"])
        self.assertLess(result["earlyMs"], 400)
        self.assertIsNone(result["timeout"])
        self.assertGreaterEqual(result["timeoutMs"], 75)
        self.assertTrue(result["settled"])
        self.assertLess(result["settledMs"], 1000)


class ExtensionSkipTest(unittest.TestCase):
    def test_send_steps_skip_matching_marketplaces_and_unchanged_saves(self):
        source = background_source()
        build = source[source.index("function buildJobSteps"):source.index("function sleep(ms)")]
        fill = source[source.index("// True when a fill log shows any control was written"):source.index("async function auditMarketplace")]
        script = """
const log = () => {};
const durableItemId = (id) => id;
const openVendooListing = 1, waitForContentScript = 1, checkDraftSafety = 1, uploadPhotos = 1;
const clearGeneral = 1, fillGeneral = 1, saveGeneral = 1, auditGeneral = 1, discoverSchema = 1;
const clearMarketplace = 1, auditMarketplace = 1, auditAllMarketplaces = 1, selectGeneralCategoryOnly = 1;
const sent = [];
const sendToVendoo = async (job, command) => {
  sent.push(command.type);
  if (command.type === 'FILL_MARKETPLACE') {
    return {ok: true, fill_log: {entries: command.platform === 'etsy'
      ? [{status: 'filled', reason: 'Already set'}, {status: 'skipped'}]
      : [{status: 'filled', reason: ''}]}};
  }
  return {ok: true};
};
""" + build + fill + """
(async () => {
  const job = {vendoo_item_id: 'item-1', options: {platforms: ['ebay', 'etsy', 'depop'], skipPlatforms: ['ebay'],
    reuseExistingItem: true, skipDiscoverSchema: true}};
  const steps = buildJobSteps(job).map((step) => step.step);
  await fillMarketplace(job, 'etsy');
  await fillMarketplace(job, 'depop');
  const etsySave = await saveMarketplace(job, 'etsy');
  const depopSave = await saveMarketplace(job, 'depop');
  console.log(JSON.stringify({steps, etsySave, depopSave, sent}));
})();
"""
        result = _node(script)
        self.assertNotIn("filling_ebay", result["steps"])
        self.assertIn("filling_etsy", result["steps"])
        self.assertTrue(result["etsySave"]["skipped"])
        self.assertNotIn("skipped", result["depopSave"])
        self.assertEqual(result["sent"].count("SAVE_MARKETPLACE"), 1)
