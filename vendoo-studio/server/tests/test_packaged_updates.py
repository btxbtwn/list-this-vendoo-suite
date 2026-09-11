from __future__ import annotations

import json
import os
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
