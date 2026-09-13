from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

EXTENSION_DIR = Path(__file__).resolve().parents[3] / "vendoo-extension"


class RetryGeneralFormTest(unittest.TestCase):
    def test_retry_opens_existing_draft_on_general(self) -> None:
        background = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
        self.assertIn("marketplace: 'general'", background)
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
