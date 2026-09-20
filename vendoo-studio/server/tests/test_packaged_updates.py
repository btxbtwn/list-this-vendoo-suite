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
        self._app = os.environ.get("VENDOO_STUDIO_APP_PATH")
        self._skip_codesign = os.environ.get("VENDOO_STUDIO_SKIP_CODESIGN")
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
        if self._app is None:
            os.environ.pop("VENDOO_STUDIO_APP_PATH", None)
        else:
            os.environ["VENDOO_STUDIO_APP_PATH"] = self._app
        if self._skip_codesign is None:
            os.environ.pop("VENDOO_STUDIO_SKIP_CODESIGN", None)
        else:
            os.environ["VENDOO_STUDIO_SKIP_CODESIGN"] = self._skip_codesign
        self.tmp.cleanup()

    def test_local_build_info_reads_stamp(self):
        info = packaged_updates.local_build_info()
        self.assertEqual(info["sha"], "aaa1111")

    def test_release_asset_url_uses_download_cdn(self):
        url = packaged_updates.release_asset_url("build_info.json")
        self.assertEqual(
            url,
            "https://github.com/btxbtwn/list-this-vendoo-suite/releases/download/studio-macos/build_info.json",
        )

    def test_api_headers_include_optional_token(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "secret-token"}, clear=False):
            headers = packaged_updates._headers(api=True)
        self.assertEqual(headers["Authorization"], "Bearer secret-token")
        self.assertEqual(headers["Accept"], "application/vnd.github+json")
        download_headers = packaged_updates._headers()
        self.assertNotIn("Authorization", download_headers)

    @patch.object(
        packaged_updates,
        "fetch_remote_build_info",
        return_value={
            "sha": "bbb2222",
            "short_sha": "bbb2222",
            "version": "0.1.0",
            "ref": "main",
            "zip_sha256": "ab" * 32,
            "title": "",
        },
    )
    def test_newer_github_sha_is_available(self, _remote):
        status = packaged_updates.check_for_packaged_update()
        self.assertTrue(status["available"])
        self.assertTrue(status["packaged"])
        self.assertEqual(status["remote_sha"], "bbb2222")
        self.assertEqual(
            status["download_url"],
            "https://github.com/btxbtwn/list-this-vendoo-suite/releases/download/studio-macos/List-This-Studio-macos.zip",
        )
        self.assertEqual(status["sha256"], "ab" * 32)
        self.assertEqual(status["summary"], "")

    @patch.object(
        packaged_updates,
        "fetch_remote_build_info",
        return_value={
            "sha": "bbb2222",
            "short_sha": "bbb2222",
            "version": "0.1.0",
            "ref": "main",
            "zip_sha256": "ab" * 32,
            "title": "Prompt to pull when Vendoo is saved",
        },
    )
    def test_summary_prefers_published_title(self, _remote):
        status = packaged_updates.check_for_packaged_update()
        self.assertTrue(status["available"])
        self.assertEqual(status["summary"], "Prompt to pull when Vendoo is saved")
        self.assertEqual(status["commits"], ["Prompt to pull when Vendoo is saved"])

    @patch.object(
        packaged_updates,
        "fetch_remote_build_info",
        return_value={
            "sha": "aaa1111",
            "short_sha": "aaa1111",
            "version": "0.1.0",
            "ref": "main",
            "zip_sha256": "ab" * 32,
            "title": "Same build",
        },
    )
    def test_same_sha_is_current(self, _remote):
        status = packaged_updates.check_for_packaged_update()
        self.assertFalse(status["available"])
        self.assertEqual(status["local_sha"], "aaa1111")
        self.assertEqual(status["summary"], "")
        self.assertIsNone(status["error"])

    def test_check_surfaces_cdn_errors(self):
        with patch.object(
            packaged_updates,
            "fetch_remote_build_info",
            side_effect=packaged_updates.PackagedUpdateError("Could not reach GitHub releases: boom"),
        ):
            status = packaged_updates.check_for_packaged_update()
        self.assertFalse(status["available"])
        self.assertIn("Could not reach GitHub releases", status["error"])

    def test_rate_limit_message_from_api_response(self):
        response = type(
            "Response",
            (),
            {
                "status_code": 403,
                "text": "API rate limit exceeded for 1.2.3.4",
            },
        )()
        message = packaged_updates._rate_limit_message(response)
        self.assertIsNotNone(message)
        self.assertIn("rate limit", message.lower())

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

    def test_extract_rejects_escaping_symbolic_links_before_ditto(self):
        archive = Path(self.tmp.name) / "symlink.zip"
        link = zipfile.ZipInfo("List This Studio.app/Contents/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(archive, "w") as bundle:
            # Three levels up leaves the extract root (app → payload → destination → parent).
            bundle.writestr(link, "../../../outside")
        with patch("subprocess.run") as run:
            with self.assertRaisesRegex(packaged_updates.PackagedUpdateError, "unsafe symbolic link"):
                packaged_updates._extract_app(archive, Path(self.tmp.name) / "symlink-output")
        run.assert_not_called()

    def test_extract_rejects_absolute_symbolic_links_before_ditto(self):
        archive = Path(self.tmp.name) / "abs-symlink.zip"
        link = zipfile.ZipInfo("List This Studio.app/Contents/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr(link, "/etc/passwd")
        with patch("subprocess.run") as run:
            with self.assertRaisesRegex(packaged_updates.PackagedUpdateError, "unsafe symbolic link"):
                packaged_updates._extract_app(archive, Path(self.tmp.name) / "abs-symlink-output")
        run.assert_not_called()

    def test_validate_allows_relative_in_bundle_symbolic_links(self):
        archive = Path(self.tmp.name) / "safe-symlink.zip"
        link = zipfile.ZipInfo("List This Studio.app/Contents/Frameworks/Python.framework/Versions/Current")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("List This Studio.app/Contents/Info.plist", "plist")
            bundle.writestr(link, "3.12")
        destination = Path(self.tmp.name) / "safe-symlink-output"
        destination.mkdir()
        # Must not raise — PyInstaller macOS zips ship dozens of in-bundle relative links.
        packaged_updates._validate_zip_members(archive, destination)

    def test_extract_app_accepts_archive_with_relative_symbolic_links(self):
        archive = Path(self.tmp.name) / "safe-symlink-extract.zip"
        link = zipfile.ZipInfo("List This Studio.app/Contents/Frameworks/Current")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("List This Studio.app/Contents/Info.plist", "plist")
            bundle.writestr("List This Studio.app/Contents/Frameworks/3.12/marker", "ok")
            bundle.writestr(link, "3.12")
        extracted = packaged_updates._extract_app(archive, Path(self.tmp.name) / "safe-symlink-extract-output")
        self.assertEqual(extracted.name, "List This Studio.app")
        self.assertTrue((extracted / "Contents" / "Info.plist").is_file())

    def test_prepare_app_bundle_makes_launcher_executable(self):
        app = Path(self.tmp.name) / "List This Studio.app"
        launcher = app / "Contents" / "MacOS" / "ListThisStudio"
        launcher.parent.mkdir(parents=True)
        launcher.write_text("#!/bin/sh\n", encoding="utf-8")
        launcher.chmod(0o644)
        packaged_updates._prepare_app_bundle(app)
        self.assertTrue(os.access(launcher, os.X_OK))

    def test_verify_app_signature_accepts_adhoc_display(self):
        app = Path(self.tmp.name) / "List This Studio.app"
        app.mkdir()

        def fake_run(args, capture_output=True, text=True):
            self.assertEqual(args[:2], ["/usr/bin/codesign", "-dv"])
            return type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "Signature=adhoc\nIdentifier=local.listthis.studio\n",
                },
            )()

        with patch.object(packaged_updates.subprocess, "run", side_effect=fake_run):
            packaged_updates._verify_app_signature(app)

    def test_verify_app_signature_rejects_unsigned(self):
        app = Path(self.tmp.name) / "List This Studio.app"
        app.mkdir()

        def fake_run(args, capture_output=True, text=True):
            return type(
                "Result",
                (),
                {
                    "returncode": 1,
                    "stdout": "",
                    "stderr": f"{app}: code object is not signed at all",
                },
            )()

        with patch.object(packaged_updates.subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(packaged_updates.PackagedUpdateError, "not signed"):
                packaged_updates._verify_app_signature(app)

    def test_force_reinstall_downloads_even_when_current(self):
        archive = Path(self.tmp.name) / "payload.zip"
        archive.write_bytes(b"zip-bytes")
        app = Path(self.tmp.name) / "installed" / "List This Studio.app"
        (app / "Contents" / "MacOS").mkdir(parents=True)
        (app / "Contents" / "MacOS" / "List This Studio").write_text("old", encoding="utf-8")
        new_app = Path(self.tmp.name) / "fresh" / "List This Studio.app"
        (new_app / "Contents" / "MacOS").mkdir(parents=True)
        os.environ["VENDOO_STUDIO_APP_PATH"] = str(app)
        os.environ["VENDOO_STUDIO_DATA_DIR"] = str(Path(self.tmp.name) / "data")
        os.environ["VENDOO_STUDIO_SKIP_CODESIGN"] = "1"

        def fake_download(_client, _url, destination: Path) -> None:
            destination.write_bytes(archive.read_bytes())

        remote = {
            "sha": "aaa1111",
            "short_sha": "aaa1111",
            "version": "0.1.0",
            "ref": "main",
            "zip_sha256": "ab" * 32,
            "title": "Current",
        }
        with (
            patch.object(packaged_updates, "fetch_remote_build_info", return_value=remote),
            patch.object(packaged_updates, "_download", side_effect=fake_download),
            patch.object(packaged_updates, "_sha256_file", return_value="ab" * 32),
            patch.object(packaged_updates, "_extract_app", return_value=new_app),
            patch.object(packaged_updates, "_verify_app_signature"),
            patch.object(packaged_updates, "_prepare_app_bundle"),
            patch.object(packaged_updates.subprocess, "Popen") as popen,
        ):
            skipped = packaged_updates.apply_packaged_update()
            forced = packaged_updates.reinstall_packaged_app()
        self.assertFalse(skipped["updated"])
        self.assertTrue(forced["updated"])
        self.assertTrue(forced["reinstalled"])
        popen.assert_called_once()

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
