from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vendoo_studio.services import chrome_bridge


class ChromeBridgeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data = root / "data"
        self.extension = root / "extension"
        self.extension.mkdir()
        (self.extension / "manifest.json").write_text("{}", encoding="utf-8")
        (self.extension / "background.js").write_text("console.log('ok')\n", encoding="utf-8")
        (self.extension / ".playwright-mcp").mkdir()
        (self.extension / ".playwright-mcp" / "trace.log").write_text("nope\n", encoding="utf-8")
        (self.extension / "README.md").write_text("skip\n", encoding="utf-8")
        self._data = os.environ.get("VENDOO_STUDIO_DATA_DIR")
        self._ext = os.environ.get("VENDOO_STUDIO_EXTENSION_DIR")
        os.environ["VENDOO_STUDIO_DATA_DIR"] = str(self.data)
        os.environ["VENDOO_STUDIO_EXTENSION_DIR"] = str(self.extension)

    def tearDown(self) -> None:
        if self._data is None:
            os.environ.pop("VENDOO_STUDIO_DATA_DIR", None)
        else:
            os.environ["VENDOO_STUDIO_DATA_DIR"] = self._data
        if self._ext is None:
            os.environ.pop("VENDOO_STUDIO_EXTENSION_DIR", None)
        else:
            os.environ["VENDOO_STUDIO_EXTENSION_DIR"] = self._ext
        self.tmp.cleanup()

    def test_sync_copies_extension_and_skips_junk(self):
        installed = chrome_bridge.sync_bundled_extension()
        self.assertTrue((installed / "manifest.json").is_file())
        self.assertTrue((installed / "background.js").is_file())
        self.assertFalse((installed / ".playwright-mcp").exists())
        self.assertFalse((installed / "README.md").exists())

    def test_install_is_idempotent_until_source_changes(self):
        self.assertTrue(chrome_bridge.install_bundled_extension())
        self.assertFalse(chrome_bridge.install_bundled_extension())
        (self.extension / "background.js").write_text("console.log('updated')\n", encoding="utf-8")
        self.assertTrue(chrome_bridge.install_bundled_extension())
        installed = chrome_bridge.installed_extension_dir()
        self.assertEqual(
            (installed / "background.js").read_text(encoding="utf-8"),
            "console.log('updated')\n",
        )
        (self.extension / "extra.js").write_text("gone\n", encoding="utf-8")
        chrome_bridge.install_bundled_extension()
        (self.extension / "extra.js").unlink()
        self.assertTrue(chrome_bridge.install_bundled_extension())
        self.assertFalse((installed / "extra.js").exists())

    def test_pending_reload_token_round_trip(self):
        self.assertIsNone(chrome_bridge.pending_extension_reload_token())
        token = chrome_bridge.mark_extension_reload_pending()
        self.assertEqual(chrome_bridge.pending_extension_reload_token(), token)
        chrome_bridge.clear_extension_reload_pending()
        self.assertIsNone(chrome_bridge.pending_extension_reload_token())

    def test_needs_worker_reload(self):
        self.assertTrue(chrome_bridge.needs_worker_reload(None, None, True))
        self.assertTrue(chrome_bridge.needs_worker_reload("abc", None, False))
        self.assertTrue(chrome_bridge.needs_worker_reload("abc", "xyz", False))
        self.assertFalse(chrome_bridge.needs_worker_reload("abc", "abc", False))
        self.assertFalse(chrome_bridge.needs_worker_reload(None, None, False))
        self.assertTrue(chrome_bridge.needs_worker_reload("abc", "abc", True))

    def test_launch_args_load_extension_into_private_profile(self):
        args = chrome_bridge.launch_args(
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/tmp/ext"),
            Path("/tmp/profile"),
        )
        self.assertIn("--load-extension=/tmp/ext", args)
        self.assertIn("--user-data-dir=/tmp/profile", args)
        self.assertIn("--disable-features=DisableLoadExtensionCommandLineSwitch", args)
        self.assertEqual(args[-1], "https://web.vendoo.co")

    def test_launch_args_open_listing_url(self):
        args = chrome_bridge.launch_args(
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/tmp/ext"),
            Path("/tmp/profile"),
            "https://web.vendoo.co/app/item/abc123",
        )
        self.assertEqual(args[-1], "https://web.vendoo.co/app/item/abc123")

    def test_launch_args_reject_non_vendoo_url(self):
        args = chrome_bridge.launch_args(
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/tmp/ext"),
            Path("/tmp/profile"),
            "https://evil.example/phishing",
        )
        self.assertEqual(args[-1], "https://web.vendoo.co")

    def test_listing_url_for_job(self):
        self.assertEqual(
            chrome_bridge.listing_url_for_job("abc123", "https://web.vendoo.co/app/item/abc123"),
            "https://web.vendoo.co/app/item/abc123",
        )
        self.assertEqual(
            chrome_bridge.listing_url_for_job("abc123", None),
            "https://web.vendoo.co/app/item/abc123",
        )
        self.assertIsNone(chrome_bridge.listing_url_for_job("new", None))
        self.assertIsNone(chrome_bridge.listing_url_for_job(None, "https://evil.example/item/abc"))
        self.assertIsNone(chrome_bridge.listing_url_for_job("../etc/passwd", None))

    def test_launch_studio_chrome_rejects_non_vendoo_url(self):
        with patch.object(chrome_bridge, "chrome_executable", return_value=Path("/bin/chrome")):
            with self.assertRaises(chrome_bridge.ChromeBridgeError) as raised:
                chrome_bridge.launch_studio_chrome("https://evil.example")
        self.assertIn("not a Vendoo listing URL", str(raised.exception))

    def test_missing_chrome_is_a_clear_error(self):
        with patch.object(chrome_bridge, "chrome_executable", return_value=None):
            with self.assertRaises(chrome_bridge.ChromeBridgeError) as raised:
                chrome_bridge.launch_studio_chrome()
        self.assertIn("Google Chrome is not installed", str(raised.exception))
