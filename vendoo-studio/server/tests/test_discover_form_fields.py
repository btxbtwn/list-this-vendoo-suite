from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from vendoo_studio.routes import extension as extension_routes

EXTENSION_DIR = Path(__file__).resolve().parents[3] / "vendoo-extension"


class DiscoverAllFormFieldsTest(unittest.TestCase):
    def test_vendoo_get_timeout_allows_full_marketplace_walk(self) -> None:
        self.assertGreaterEqual(extension_routes.VENDOO_GET_TIMEOUT_SEC, 120)

    def test_get_vendoo_item_command_timeout_allows_discovery(self) -> None:
        text = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
        start = text.index("function commandTimeoutMs")
        end = text.index("function compactVendooValue")
        script = text[start:end] + """
const result = {
  getItem: commandTimeoutMs({ type: 'GET_VENDOO_ITEM' }),
  discover: commandTimeoutMs({ type: 'DISCOVER_SCHEMA', platforms: ['ebay', 'etsy', 'poshmark', 'mercari', 'depop'] }),
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
        self.assertGreaterEqual(result["getItem"], 120000)
        self.assertGreaterEqual(result["discover"], 120000)

    def test_job_steps_discover_schema_before_marketplace_fill(self) -> None:
        text = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
        start = text.index("function buildJobSteps(job)")
        end = text.index("const NEW_ITEM_URL")
        script = text[start:end] + """
const steps = buildJobSteps({
  options: { platforms: ['ebay', 'poshmark'], clearBeforeFill: false, skipPhotos: true },
}).map((step) => step.step);
console.log(JSON.stringify(steps));
"""
        # Provide no-op fns referenced by buildJobSteps when the slice is executed alone.
        preamble = """
const openVendooListing = async () => ({ ok: true });
const waitForContentScript = async () => ({ ok: true });
const uploadPhotos = async () => ({ ok: true });
const clearGeneral = async () => ({ ok: true });
const fillGeneral = async () => ({ ok: true });
const saveGeneral = async () => ({ ok: true });
const auditGeneral = async () => ({ ok: true });
const discoverSchema = async () => ({ ok: true });
const clearMarketplace = async () => ({ ok: true });
const fillMarketplace = async () => ({ ok: true });
const saveMarketplace = async () => ({ ok: true });
const auditMarketplace = async () => ({ ok: true });
"""
        proc = subprocess.run(
            ["node", "-e", preamble + script],
            check=True,
            capture_output=True,
            text=True,
        )
        steps = json.loads(proc.stdout)
        self.assertIn("discovering_schema", steps)
        self.assertLess(steps.index("auditing_general"), steps.index("discovering_schema"))
        self.assertLess(steps.index("discovering_schema"), steps.index("filling_ebay"))
        self.assertLess(steps.index("discovering_schema"), steps.index("filling_poshmark"))

    def test_content_script_discovers_each_marketplace_form(self) -> None:
        content = (EXTENSION_DIR / "content-scripts" / "vendoo.js").read_text(encoding="utf-8")
        self.assertIn("async function discoverAllMarketplaceListings", content)
        self.assertIn("async function discoverMarketplaceSchema", content)
        self.assertIn("waitForEbayOptionalCategoryFields", content)
        self.assertIn("discoverAllMarketplaceListings(", content)
        self.assertIn("DISCOVER_SCHEMA", content)
        self.assertIn("fillMarketplaceCategory(platform, data)", content)
        for platform in ("ebay", "etsy", "poshmark", "mercari", "depop"):
            self.assertIn(f"'{platform}'", content)
            self.assertIn(f"await fillMarketplaceCategory('{platform}'", content)


if __name__ == "__main__":
    unittest.main()
