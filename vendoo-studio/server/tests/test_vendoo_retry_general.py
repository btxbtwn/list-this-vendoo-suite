from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

EXTENSION_DIR = Path(__file__).resolve().parents[3] / "vendoo-extension"


class RetryGeneralFormTest(unittest.TestCase):
    def test_retry_opens_existing_draft_on_general(self) -> None:
        background = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
        self.assertIn("marketplace: resumeMarketplace", background)
        self.assertIn("function marketplaceFromStep", background)
        self.assertIn("function withMarketplaceQuery", background)
        self.assertIn("function listingUrlsMatch", background)
        self.assertIn("waitForTabComplete(tabId, 20000, url)", background)

    def test_fill_general_switches_tab_and_waits_for_category(self) -> None:
        content = (EXTENSION_DIR / "content-scripts" / "vendoo.js").read_text(encoding="utf-8")
        self.assertIn("await activateMarketplaceSection('general')", content)
        self.assertIn("waitForGeneralCategoryControl", content)
        self.assertIn("findGeneralCategoryControl", content)

    def test_listing_url_helpers_force_general_marketplace(self) -> None:
        text = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
        start = text.index("function withMarketplaceQuery")
        end = text.index("function isTabReady")
        script = text[start:end] + """
const item = 'https://web.vendoo.co/app/item/eC65xKL';
const ebay = 'https://web.vendoo.co/app/item/eC65xKL?marketplace=ebay';
const general = withMarketplaceQuery(item, 'general');
const result = {
  general,
  ebayToGeneral: withMarketplaceQuery(ebay, 'general'),
  sameGeneral: listingUrlsMatch(general, withMarketplaceQuery(item, 'general')),
  ebayVsGeneral: listingUrlsMatch(ebay, withMarketplaceQuery(item, 'general')),
  missingVsGeneral: listingUrlsMatch(item, withMarketplaceQuery(item, 'general')),
  otherItem: listingUrlsMatch(
    'https://web.vendoo.co/app/item/other?marketplace=general',
    withMarketplaceQuery(item, 'general'),
  ),
};
console.log(JSON.stringify(result));
"""
        proc = subprocess.run(
            ["node", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(proc.stdout)
        self.assertEqual(result["general"], "https://web.vendoo.co/app/item/eC65xKL?marketplace=general")
        self.assertEqual(result["ebayToGeneral"], "https://web.vendoo.co/app/item/eC65xKL?marketplace=general")
        self.assertTrue(result["sameGeneral"])
        self.assertFalse(result["ebayVsGeneral"])
        self.assertFalse(result["missingVsGeneral"])
        self.assertFalse(result["otherItem"])

    def test_select_job_steps_resumes_from_failed_marketplace(self) -> None:
        text = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
        start = text.index("function marketplaceFromStep")
        end = text.index("async function runJob")
        helpers = text[start:end]
        script = helpers + """
function log() {}
const steps = [
  { step: 'opening_vendoo' },
  { step: 'waiting_ready' },
  { step: 'checking_draft_safety' },
  { step: 'uploading_photos' },
  { step: 'filling_general' },
  { step: 'saving_general' },
  { step: 'auditing_general' },
  { step: 'discovering_schema' },
  { step: 'filling_ebay' },
  { step: 'saving_ebay' },
  { step: 'filling_etsy' },
  { step: 'saving_etsy' },
  { step: 'filling_depop' },
  { step: 'saving_depop' },
];
const resumed = selectJobSteps({ options: { resumeFrom: 'filling_etsy', reuseExistingItem: true } }, steps);
const auditSteps = [
  { step: 'opening_vendoo' },
  { step: 'waiting_ready' },
  { step: 'checking_draft_safety' },
  { step: 'auditing_depop' },
];
const auditResume = selectJobSteps({ options: { resumeFrom: 'auditing_depop', reuseExistingItem: true } }, auditSteps);
const newItemResume = selectJobSteps({ options: { resumeFrom: 'filling_etsy' } }, steps.filter((step) => step.step !== 'checking_draft_safety'));
const full = selectJobSteps({ options: {} }, steps);
const missing = selectJobSteps({ options: { resumeFrom: 'filling_facebook' } }, steps);
const result = {
  resumed: resumed.map((step) => step.step),
  auditResume: auditResume.map((step) => step.step),
  newItemResume: newItemResume.map((step) => step.step),
  fullCount: full.length,
  missingCount: missing.length,
  etsyMarketplace: marketplaceFromStep('filling_etsy'),
  generalMarketplace: marketplaceFromStep('filling_general'),
  schemaMarketplace: marketplaceFromStep('discovering_schema'),
  depopAuditMarketplace: marketplaceFromStep('auditing_depop'),
  saveEbayMarketplace: marketplaceFromStep('saving_ebay'),
};
console.log(JSON.stringify(result));
"""
        proc = subprocess.run(
            ["node", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(proc.stdout)
        self.assertEqual(
            result["resumed"],
            ["opening_vendoo", "waiting_ready", "checking_draft_safety", "filling_etsy", "saving_etsy", "filling_depop", "saving_depop"],
        )
        self.assertEqual(
            result["auditResume"],
            ["opening_vendoo", "waiting_ready", "checking_draft_safety", "auditing_depop"],
        )
        self.assertEqual(
            result["newItemResume"],
            ["opening_vendoo", "waiting_ready", "filling_etsy", "saving_etsy", "filling_depop", "saving_depop"],
        )
        self.assertEqual(result["fullCount"], 14)
        self.assertEqual(result["missingCount"], 14)
        self.assertEqual(result["etsyMarketplace"], "etsy")
        self.assertEqual(result["generalMarketplace"], "general")
        self.assertEqual(result["schemaMarketplace"], "general")
        self.assertEqual(result["depopAuditMarketplace"], "depop")
        self.assertEqual(result["saveEbayMarketplace"], "ebay")

    def test_category_search_checks_draft_safety_before_picker_click(self) -> None:
        text = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
        start = text.index("function replyCategories")
        end = text.index("async function openVendooListing", start)
        helpers = text[start:end]
        script = """
let activeJob = null;
let activePatch = null;
let safetyOk = false;
let calls = [];
let replies = [];
const chrome = { tabs: { get: async () => ({ url: '' }) } };
function extractItemIdFromUrl() { return ''; }
async function openListingForPatch() { return { ok: true, tabId: 7 }; }
async function pingContentScript() { return { ok: true }; }
async function injectVendooContentScript() {}
async function sleep() {}
function send(message) { replies.push(message); }
async function sendToVendoo(_job, message) {
  calls.push(message.type);
  if (message.type === 'WAIT_FOR_FORM') return { ok: true };
  if (message.type === 'CHECK_DRAFT_SAFETY') return safetyOk
    ? { ok: true }
    : { ok: false, error: 'published item' };
  if (message.type === 'SEARCH_CATEGORIES') return { ok: true, path: 'Women > Tops', matches: [] };
  return { ok: false };
}
""" + helpers + """
(async () => {
  const payload = {
    request_id: 'r1',
    query: 'Women Blouse',
    vendoo_item_id: 'abc123',
    platforms: ['etsy'],
  };
  await runSearchCategories('job1', payload);
  const blockedCalls = [...calls];
  const blockedReply = replies.at(-1).payload;
  calls = [];
  safetyOk = true;
  await runSearchCategories('job1', { ...payload, request_id: 'r2' });
  console.log(JSON.stringify({ blockedCalls, blockedReply, allowedCalls: calls }));
})();
"""
        proc = subprocess.run(
            ["node", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(proc.stdout)
        self.assertEqual(result["blockedCalls"], ["WAIT_FOR_FORM", "CHECK_DRAFT_SAFETY"])
        self.assertFalse(result["blockedReply"]["ok"])
        self.assertEqual(
            result["allowedCalls"],
            ["WAIT_FOR_FORM", "CHECK_DRAFT_SAFETY", "SEARCH_CATEGORIES"],
        )


if __name__ == "__main__":
    unittest.main()
