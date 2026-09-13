from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

EXTENSION_DIR = Path(__file__).resolve().parents[3] / "vendoo-extension"


class ExtensionContentScriptVersionTest(unittest.TestCase):
    def test_version_is_defined_once_and_shared(self) -> None:
        version_file = (EXTENSION_DIR / "content-script-version.js").read_text(encoding="utf-8")
        match = re.search(r"^var CONTENT_SCRIPT_VERSION = '([^']+)';\s*$", version_file.strip())
        self.assertIsNotNone(match)
        self.assertRegex(match.group(1), r"^\d+\.\d+\.\d+$")

        background = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
        self.assertIn("importScripts('content-script-version.js')", background)
        self.assertNotRegex(background, r"\bCONTENT_SCRIPT_VERSION\s*=")
        self.assertNotIn("Content script is stale", background)
        self.assertIn("Reloading Vendoo tab", background)
        self.assertIn("'content-script-version.js', 'content-scripts/vendoo.js'", background)

        content = (EXTENSION_DIR / "content-scripts" / "vendoo.js").read_text(encoding="utf-8")
        self.assertIn("globalThis.CONTENT_SCRIPT_VERSION", content)
        self.assertNotRegex(content, r"const CONTENT_SCRIPT_VERSION\s*=\s*'")

        manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8"))
        vendoo_scripts = next(
            entry["js"]
            for entry in manifest["content_scripts"]
            if "content-scripts/vendoo.js" in entry["js"]
        )
        self.assertEqual(vendoo_scripts[0], "content-script-version.js")
        self.assertIn("content-scripts/vendoo.js", vendoo_scripts)
