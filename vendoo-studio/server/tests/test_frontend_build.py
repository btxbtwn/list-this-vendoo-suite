import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from vendoo_studio.services import frontend_build


class FrontendStalenessTest(unittest.TestCase):
    """dist/ has to be recognisably the build of the checkout serving it."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dist = Path(self._tmp.name) / "dist"
        self.dist.mkdir(parents=True)
        patches = [
            mock.patch.object(frontend_build, "frontend_dist_dir", lambda: self.dist),
            mock.patch.object(frontend_build, "app_version", lambda: "0.1.46"),
            # Git answers are exercised explicitly per test.
            mock.patch.object(frontend_build, "head_sha", lambda: None),
            mock.patch.object(frontend_build, "_tree_is_dirty", lambda: False),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self._tmp.cleanup)

    def write_stamp(self, **payload):
        (self.dist / "index.html").write_text("<html></html>", encoding="utf-8")
        (self.dist / "build-stamp.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_matching_build_is_current(self):
        self.write_stamp(version="0.1.46", sha="a" * 40)
        self.assertIsNone(frontend_build.frontend_needs_build())

    def test_unbuilt_frontend_needs_building(self):
        self.assertIn("not been built", frontend_build.frontend_needs_build() or "")

    def test_unstamped_bundle_is_rebuilt(self):
        # Bundles from before this check exist in the wild; treat them as stale.
        (self.dist / "index.html").write_text("<html></html>", encoding="utf-8")
        self.assertIn("no build stamp", frontend_build.frontend_needs_build() or "")

    def test_corrupt_stamp_is_rebuilt(self):
        (self.dist / "index.html").write_text("<html></html>", encoding="utf-8")
        (self.dist / "build-stamp.json").write_text("{not json", encoding="utf-8")
        self.assertIn("no build stamp", frontend_build.frontend_needs_build() or "")

    def test_version_drift_is_caught(self):
        # The exact shape of the reported bug: backend on 0.1.46, UI on 0.1.44.
        self.write_stamp(version="0.1.44", sha="a" * 40)
        reason = frontend_build.frontend_needs_build() or ""
        self.assertIn("0.1.44", reason)
        self.assertIn("0.1.46", reason)

    def test_commit_drift_on_a_clean_checkout_is_caught(self):
        # Same version, different code — bumps do not always accompany a merge.
        self.write_stamp(version="0.1.46", sha="a" * 40)
        with mock.patch.object(frontend_build, "head_sha", lambda: "b" * 40):
            self.assertIn("commit", frontend_build.frontend_needs_build() or "")

    def test_commit_drift_is_ignored_while_editing(self):
        # A dirty tree means a dev mid-change; they run the vite dev server.
        self.write_stamp(version="0.1.46", sha="a" * 40)
        with (
            mock.patch.object(frontend_build, "head_sha", lambda: "b" * 40),
            mock.patch.object(frontend_build, "_tree_is_dirty", lambda: True),
        ):
            self.assertIsNone(frontend_build.frontend_needs_build())

    def test_stamp_without_sha_falls_back_to_version(self):
        # Source drops with no git history still build and must not loop.
        self.write_stamp(version="0.1.46")
        with mock.patch.object(frontend_build, "head_sha", lambda: "b" * 40):
            self.assertIsNone(frontend_build.frontend_needs_build())


class InstallPreserveTest(unittest.TestCase):
    def test_dist_is_not_carried_across_a_reinstall(self):
        from vendoo_studio.services.updates import INSTALL_PRESERVE

        self.assertNotIn("vendoo-studio/dist", INSTALL_PRESERVE)


if __name__ == "__main__":
    unittest.main()
