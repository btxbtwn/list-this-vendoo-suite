from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from vendoo_studio.services import packaged_updates


class PackagedUpdateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.info = root / "build_info.json"
        self.info.write_text(json.dumps({"version": "0.1.0", "sha": "aaa1111", "short_sha": "aaa1111", "ref": "main"}), encoding="utf-8")
        self._packaged = os.environ.get("VENDOO_STUDIO_PACKAGED")
        self._info = os.environ.get("VENDOO_STUDIO_BUILD_INFO")
        self._data = os.environ.get("VENDOO_STUDIO_DATA_DIR")
        os.environ["VENDOO_STUDIO_PACKAGED"] = "1"
        os.environ["VENDOO_STUDIO_BUILD_INFO"] = str(self.info)

    def tearDown(self) -> None:
        if self._packaged is None:
            os.environ.pop("VENDOO_STUDIO_PACKAGED", None)
        else:
            os.environ["VENDOO_STUDIO_PACKAGED"] = self._packaged
        if self._info is None:
            os.environ.pop("VENDOO_STUDIO_BUILD_INFO", None)
        else:
            os.environ["VENDOO_STUDIO_BUILD_INFO"] = self._info
        if self._data is None:
            os.environ.pop("VENDOO_STUDIO_DATA_DIR", None)
        else:
            os.environ["VENDOO_STUDIO_DATA_DIR"] = self._data
        self.tmp.cleanup()

    def test_local_build_info_reads_stamp(self):
        info = packaged_updates.local_build_info()
        self.assertEqual(info["sha"], "aaa1111")

    @patch.object(packaged_updates, "remote_build_info", return_value={"sha": "bbb2222", "short_sha": "bbb2222", "version": "0.1.0", "ref": "main"})
    @patch.object(
        packaged_updates,
        "fetch_release",
        return_value={
            "name": "List This Studio (macOS)",
            "body": "sha: bbb2222",
            "html_url": "https://github.com/btxbtwn/list-this-vendoo-suite/releases/tag/studio-macos",
            "assets": [{
                "name": "List-This-Studio-macos.zip",
                "browser_download_url": "https://example.com/List-This-Studio-macos.zip",
            }],
        },
    )
    def test_newer_github_sha_is_available(self, _fetch, _remote):
        status = packaged_updates.check_for_packaged_update()
        self.assertTrue(status["available"])
        self.assertTrue(status["packaged"])
        self.assertEqual(status["remote_sha"], "bbb2222")
        self.assertEqual(status["download_url"], "https://example.com/List-This-Studio-macos.zip")

    @patch.object(packaged_updates, "remote_build_info", return_value={"sha": "aaa1111", "short_sha": "aaa1111", "version": "0.1.0", "ref": "main"})
    @patch.object(
        packaged_updates,
        "fetch_release",
        return_value={
            "name": "List This Studio (macOS)",
            "body": "sha: aaa1111",
            "assets": [{
                "name": "List-This-Studio-macos.zip",
                "browser_download_url": "https://example.com/List-This-Studio-macos.zip",
            }],
        },
    )
    def test_same_sha_is_current(self, _fetch, _remote):
        status = packaged_updates.check_for_packaged_update()
        self.assertFalse(status["available"])
        self.assertEqual(status["local_sha"], "aaa1111")

    def test_extract_app_finds_keepparent_bundle(self):
        archive = Path(self.tmp.name) / "List-This-Studio-macos.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("List This Studio.app/Contents/Info.plist", "plist")
        extracted = packaged_updates._extract_app(archive, Path(self.tmp.name) / "unpacked")
        self.assertTrue(extracted.is_dir())
        self.assertEqual(extracted.name, "List This Studio.app")

    def test_extract_app_finds_bundle_next_to_how_to_open(self):
        archive = Path(self.tmp.name) / "List-This-Studio-macos.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("How to Open.txt", "open me")
            bundle.writestr("List This Studio.app/Contents/Info.plist", "plist")
        extracted = packaged_updates._extract_app(archive, Path(self.tmp.name) / "unpacked-guide")
        self.assertEqual(extracted.name, "List This Studio.app")

    def test_extract_rejects_traversal_before_ditto(self):
        archive = Path(self.tmp.name) / "unsafe.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("../outside.txt", "unsafe")
        with patch("subprocess.run") as run:
            with self.assertRaises(packaged_updates.PackagedUpdateError):
                packaged_updates._extract_app(archive, Path(self.tmp.name) / "unsafe-output")
        run.assert_not_called()

    def test_extract_rejects_symbolic_links_before_ditto(self):
        archive = Path(self.tmp.name) / "symlink.zip"
        link = zipfile.ZipInfo("List This Studio.app/Contents/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr(link, "../../outside")
        with patch("subprocess.run") as run:
            with self.assertRaises(packaged_updates.PackagedUpdateError):
                packaged_updates._extract_app(archive, Path(self.tmp.name) / "symlink-output")
        run.assert_not_called()

    def test_prepare_app_bundle_makes_launcher_executable(self):
        app = Path(self.tmp.name) / "List This Studio.app"
        launcher = app / "Contents" / "MacOS" / "ListThisStudio"
        launcher.parent.mkdir(parents=True)
        launcher.write_text("#!/bin/sh\n", encoding="utf-8")
        launcher.chmod(0o644)
        packaged_updates._prepare_app_bundle(app)
        self.assertTrue(os.access(launcher, os.X_OK))

    def test_replacer_clears_quarantine_before_relaunch(self):
        root = Path(self.tmp.name)
        app = root / "List This Studio.app"
        new_app = root / "new" / "List This Studio.app"
        (app / "Contents" / "MacOS").mkdir(parents=True)
        os.environ["VENDOO_STUDIO_DATA_DIR"] = str(root / "data")
        script = packaged_updates._write_replacer(app, new_app, 12345)
        text = script.read_text(encoding="utf-8")
        self.assertIn("xattr -cr", text)
        self.assertIn("chmod -R u+x", text)
        self.assertIn("/usr/bin/open", text)
