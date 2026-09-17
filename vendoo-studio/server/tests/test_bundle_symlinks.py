from __future__ import annotations

import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from vendoo_studio.services import bundle_symlinks, packaged_updates


class BundleSymlinkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_flatten_replaces_relative_symlinks(self):
        app = self.root / "List This Studio.app" / "Contents"
        versions = app / "Frameworks" / "Python.framework" / "Versions"
        real = versions / "3.12"
        real.mkdir(parents=True)
        (real / "Python").write_text("bin", encoding="utf-8")
        current = versions / "Current"
        current.symlink_to("3.12")
        count = bundle_symlinks.flatten_symlinks(self.root / "List This Studio.app")
        self.assertEqual(count, 1)
        self.assertFalse(current.is_symlink())
        self.assertTrue(current.is_dir())
        self.assertEqual((current / "Python").read_text(encoding="utf-8"), "bin")

    def test_flatten_rejects_external_symlinks(self):
        app = self.root / "app"
        app.mkdir()
        outside = self.root / "outside.txt"
        outside.write_text("nope", encoding="utf-8")
        link = app / "escape"
        link.symlink_to(outside)
        with self.assertRaises(bundle_symlinks.BundleSymlinkError):
            bundle_symlinks.flatten_symlinks(app)

    def test_flattened_tree_zips_without_symlink_members(self):
        app = self.root / "List This Studio.app" / "Contents" / "MacOS"
        app.mkdir(parents=True)
        (app / "List This Studio").write_text("bin", encoding="utf-8")
        sibling = self.root / "List This Studio.app" / "Contents" / "Resources"
        sibling.mkdir(parents=True)
        (sibling / "marker").write_text("ok", encoding="utf-8")
        link = self.root / "List This Studio.app" / "Contents" / "Frameworks"
        link.symlink_to("Resources")
        bundle_symlinks.flatten_symlinks(self.root / "List This Studio.app")

        archive = self.root / "out.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            base = self.root / "List This Studio.app"
            for path in base.rglob("*"):
                if path.is_dir():
                    continue
                zf.write(path, path.relative_to(self.root).as_posix())

        bundle_symlinks.assert_zip_has_no_symlinks(archive)
        packaged_updates._validate_zip_members(archive, self.root / "extract")

    def test_assert_zip_has_no_symlinks_fails_on_link_member(self):
        archive = self.root / "linked.zip"
        link = zipfile.ZipInfo("List This Studio.app/Contents/Current")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("List This Studio.app/Contents/Info.plist", "plist")
            zf.writestr(link, "3.12")
        with self.assertRaises(bundle_symlinks.BundleSymlinkError):
            bundle_symlinks.assert_zip_has_no_symlinks(archive)


class PackageMacosScriptTest(unittest.TestCase):
    def test_package_script_resigns_after_flatten(self):
        """Flattening invalidates PyInstaller's signature; shipping without re-sign
        makes macOS refuse to open the zip app (see studio-macos packaging)."""
        script = (
            Path(__file__).resolve().parents[2] / "scripts" / "package-macos-app.sh"
        )
        text = script.read_text(encoding="utf-8")
        flatten_at = text.index("flatten_symlinks")
        resign_at = text.index("codesign --force --sign")
        self.assertGreater(
            resign_at,
            flatten_at,
            "package-macos-app.sh must re-sign after flatten_symlinks",
        )
        # --deep fails on flattened metadata dirs (e.g. numpy-*.dist-info).
        self.assertNotIn("codesign --force --deep --sign", text)
        # codesign -dv alone is not enough: it can still print a stale DR after
        # flatten without proving the signature was rewritten.
        self.assertIn("Re-signing flattened app", text)
