from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import httpx

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

    def test_normalize_build_info_formats_every_pull_request(self):
        info = packaged_updates._normalize_build_info(
            {
                "sha": "bbb2222",
                "pull_requests": [
                    {"number": 42, "title": "Newest change", "url": "https://example.test/42"},
                    {"number": 41, "title": "Earlier change", "url": "https://example.test/41"},
                ],
            }
        )
        self.assertEqual(
            info["commits"],
            ["#42 — Newest change", "#41 — Earlier change"],
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
            "sha": "bbb2222",
            "short_sha": "bbb2222",
            "version": "0.1.0",
            "ref": "main",
            "zip_sha256": "ab" * 32,
            "title": "Newest change",
            "commits": ["#42 — Newest change", "#41 — Earlier change"],
        },
    )
    def test_packaged_update_includes_every_published_pull_request(self, _remote):
        status = packaged_updates.check_for_packaged_update()
        self.assertEqual(status["behind"], 2)
        self.assertEqual(status["summary"], "#42 — Newest change")
        self.assertEqual(
            status["commits"],
            ["#42 — Newest change", "#41 — Earlier change"],
        )

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

        def fake_download(_client, _url, destination: Path, _progress_callback=None) -> None:
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
            progress = []
            prepared = packaged_updates.prepare_packaged_update(force=True, progress_callback=progress.append)
            popen.assert_not_called()
            installed = packaged_updates.install_prepared_packaged_update()
            forced = packaged_updates.reinstall_packaged_app()
        self.assertFalse(skipped["updated"])
        self.assertTrue(prepared["prepared"])
        self.assertTrue(installed["updated"])
        # Phase markers keep the meter moving even when the download stub is silent.
        self.assertEqual(progress[0], 1.0)
        self.assertEqual(progress[-1], 100.0)
        self.assertGreater(max(progress), 90.0)
        self.assertTrue(forced["updated"])
        self.assertTrue(forced["reinstalled"])
        self.assertEqual(popen.call_count, 2)

    def test_map_download_progress_stays_inside_the_download_band(self):
        self.assertEqual(packaged_updates.map_download_progress(0), packaged_updates.DOWNLOAD_PROGRESS_FLOOR)
        self.assertEqual(packaged_updates.map_download_progress(100), packaged_updates.DOWNLOAD_PROGRESS_CEILING)
        mid = packaged_updates.map_download_progress(50)
        self.assertGreater(mid, packaged_updates.DOWNLOAD_PROGRESS_FLOOR)
        self.assertLess(mid, packaged_updates.DOWNLOAD_PROGRESS_CEILING)

    def test_unknown_size_download_progress_climbs_without_content_length(self):
        self.assertEqual(packaged_updates.unknown_size_download_progress(0), 0.0)
        early = packaged_updates.unknown_size_download_progress(1024 * 1024)
        later = packaged_updates.unknown_size_download_progress(50 * 1024 * 1024)
        self.assertGreater(early, 0.0)
        self.assertGreater(later, early)
        self.assertLess(later, 100.0)

    def test_download_reports_progress_with_and_without_content_length(self):
        import http.server
        import threading

        payload = b"x" * (200 * 1024)

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if self.path.endswith("no-cl"):
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                # Write in pieces so iter_bytes yields more than one chunk.
                for index in range(0, len(payload), 16 * 1024):
                    self.wfile.write(payload[index : index + 16 * 1024])

            def log_message(self, *_args):
                return

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        try:
            with httpx.Client(timeout=10.0) as client:
                with_cl: list[float] = []
                dest = Path(self.tmp.name) / "with-cl.zip"
                packaged_updates._download(
                    client,
                    f"http://127.0.0.1:{port}/file.zip",
                    dest,
                    with_cl.append,
                )
                self.assertTrue(dest.is_file())
                self.assertGreater(len(with_cl), 1)
                self.assertEqual(with_cl[-1], packaged_updates.DOWNLOAD_PROGRESS_CEILING)
                self.assertGreater(with_cl[0], packaged_updates.DOWNLOAD_PROGRESS_FLOOR - 0.01)

                no_cl: list[float] = []
                dest2 = Path(self.tmp.name) / "no-cl.zip"
                packaged_updates._download(
                    client,
                    f"http://127.0.0.1:{port}/no-cl",
                    dest2,
                    no_cl.append,
                )
                self.assertTrue(dest2.is_file())
                self.assertGreater(len(no_cl), 0)
                self.assertEqual(no_cl[-1], packaged_updates.DOWNLOAD_PROGRESS_CEILING)
        finally:
            server.shutdown()
            server.server_close()

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
