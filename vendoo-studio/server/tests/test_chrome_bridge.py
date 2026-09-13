from __future__ import annotations

import os
import signal
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

    def test_build_status_matches_bundled_version(self):
        (self.extension / "manifest.json").write_text('{"version": "0.2.6"}', encoding="utf-8")
        chrome_bridge.install_bundled_extension()
        status = chrome_bridge.extension_build_status("0.2.6", None)
        self.assertTrue(status["up_to_date"])
        self.assertFalse(status["reload_pending"])
        self.assertEqual(status["expected_version"], "0.2.6")
        self.assertEqual(status["version"], "0.2.6")

    def test_build_status_reports_version_mismatch(self):
        (self.extension / "manifest.json").write_text('{"version": "0.2.6"}', encoding="utf-8")
        chrome_bridge.install_bundled_extension()
        status = chrome_bridge.extension_build_status("0.2.5", None)
        self.assertFalse(status["up_to_date"])
        self.assertEqual(status["expected_version"], "0.2.6")
        self.assertEqual(status["version"], "0.2.5")

    def test_build_status_stale_when_source_changed(self):
        (self.extension / "manifest.json").write_text('{"version": "0.2.6"}', encoding="utf-8")
        chrome_bridge.install_bundled_extension()
        (self.extension / "background.js").write_text("console.log('new')\n", encoding="utf-8")
        status = chrome_bridge.extension_build_status("0.2.6", None)
        self.assertFalse(status["up_to_date"])
        self.assertTrue(status["reload_pending"])
        self.assertFalse(status["files_in_sync"])

    def test_build_status_stale_until_reload_generation_matches(self):
        (self.extension / "manifest.json").write_text('{"version": "0.2.6"}', encoding="utf-8")
        chrome_bridge.install_bundled_extension()
        token = chrome_bridge.mark_extension_reload_pending()
        stale = chrome_bridge.extension_build_status("0.2.6", None)
        self.assertFalse(stale["up_to_date"])
        current = chrome_bridge.extension_build_status("0.2.6", token)
        self.assertTrue(current["up_to_date"])

    def test_launch_args_open_everyday_chrome_on_macos(self):
        executable = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        with patch.object(chrome_bridge.sys, "platform", "darwin"):
            args = chrome_bridge.launch_args(executable)
        self.assertEqual(
            args,
            ["open", "-a", "/Applications/Google Chrome.app", "https://web.vendoo.co/app"],
        )

    def test_launch_args_open_listing_url(self):
        executable = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        with patch.object(chrome_bridge.sys, "platform", "darwin"):
            args = chrome_bridge.launch_args(executable, "https://web.vendoo.co/app/item/abc123")
        self.assertEqual(args[-1], "https://web.vendoo.co/app/item/abc123")

    def test_launch_args_reject_non_vendoo_url(self):
        executable = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        with patch.object(chrome_bridge.sys, "platform", "darwin"):
            args = chrome_bridge.launch_args(executable, "https://evil.example/phishing")
        self.assertEqual(args[-1], "https://web.vendoo.co/app")

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

    def test_studio_chrome_pids_match_profile_marker(self):
        profile = chrome_bridge.chrome_profile_dir().resolve()
        listing = (
            f"1234 /Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
            f"--user-data-dir={profile} --load-extension=/tmp/ext\n"
            "5678 /Applications/Google Chrome.app/Contents/MacOS/Google Chrome\n"
        )
        with patch("vendoo_studio.services.chrome_bridge.subprocess.check_output", return_value=listing):
            self.assertEqual(chrome_bridge.studio_chrome_pids(), [1234])

    def test_quit_studio_chrome_sends_sigterm(self):
        calls = {"n": 0}

        def pids() -> list[int]:
            calls["n"] += 1
            return [99] if calls["n"] == 1 else []

        with patch.object(chrome_bridge, "studio_chrome_pids", side_effect=pids), patch.object(
            chrome_bridge, "_pid_is_running", return_value=False
        ), patch("vendoo_studio.services.chrome_bridge.os.kill") as kill:
            chrome_bridge.quit_studio_chrome()
        kill.assert_called_once_with(99, signal.SIGTERM)

    def test_launch_studio_chrome_uses_everyday_chrome_on_macos(self):
        executable = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        with patch.object(chrome_bridge, "chrome_executable", return_value=executable), patch.object(
            chrome_bridge, "sync_bundled_extension", return_value=Path("/tmp/ext")
        ), patch.object(chrome_bridge, "quit_studio_chrome") as quit, patch.object(
            chrome_bridge.sys, "platform", "darwin"
        ), patch("vendoo_studio.services.chrome_bridge.subprocess.Popen") as popen:
            result = chrome_bridge.launch_studio_chrome(visible=True)
        quit.assert_called_once()
        cmd = popen.call_args[0][0]
        self.assertEqual(cmd[:3], ["open", "-a", "/Applications/Google Chrome.app"])
        self.assertEqual(cmd[-1], "https://web.vendoo.co/app")
        self.assertNotIn("-n", cmd)
        self.assertNotIn("--user-data-dir", " ".join(cmd))
        self.assertNotIn("--load-extension", " ".join(cmd))
        self.assertEqual(result["profile"], "default")

    def test_chrome_executable_finds_home_applications(self):
        root = Path(self.tmp.name) / "Applications"
        binary = root / "Google Chrome.app/Contents/MacOS/Google Chrome"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\n", encoding="utf-8")
        binary.chmod(0o755)
        with patch.object(chrome_bridge, "chrome_search_dirs", return_value=(root,)):
            self.assertEqual(chrome_bridge.chrome_executable(), binary)
