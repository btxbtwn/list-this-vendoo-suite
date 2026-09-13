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

    def test_content_script_discovers_each_marketplace_form(self) -> None:
        content = (EXTENSION_DIR / "content-scripts" / "vendoo.js").read_text(encoding="utf-8")
        self.assertIn("async function discoverAllMarketplaceListings", content)
        self.assertIn("waitForEbayOptionalCategoryFields", content)
        self.assertIn("discoverAllMarketplaceListings()", content)
        for platform in ("ebay", "etsy", "poshmark", "mercari", "depop"):
            self.assertIn(f"'{platform}'", content)


if __name__ == "__main__":
    unittest.main()
