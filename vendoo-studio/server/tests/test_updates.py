from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from vendoo_studio.services import updates


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    return (result.stdout or "").strip()


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "studio@example.com")
    _git(path, "config", "user.name", "Studio")
    (path / "README.md").write_text("one\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "first")


class ProductionUpdateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dev = os.environ.pop("VENDOO_STUDIO_DEV", None)
        self._url = os.environ.pop("VENDOO_STUDIO_UPDATE_URL", None)
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.remote = root / "remote.git"
        self.local = root / "local"
        _init_repo(self.remote)
        _git(root, "clone", str(self.remote), str(self.local))
        _git(self.local, "config", "user.email", "studio@example.com")
        _git(self.local, "config", "user.name", "Studio")
        os.environ["VENDOO_STUDIO_UPDATE_URL"] = str(self.remote)

    def tearDown(self) -> None:
        if self._dev is None:
            os.environ.pop("VENDOO_STUDIO_DEV", None)
        else:
            os.environ["VENDOO_STUDIO_DEV"] = self._dev
        if self._url is None:
            os.environ.pop("VENDOO_STUDIO_UPDATE_URL", None)
        else:
            os.environ["VENDOO_STUDIO_UPDATE_URL"] = self._url
        self.tmp.cleanup()

    def test_production_update_discards_dirty_files_and_pins_main(self):
        _git(self.remote, "commit", "--allow-empty", "-m", "second")
        (self.local / "README.md").write_text("local dirt\n", encoding="utf-8")

        status = updates.check_for_updates_at(self.local)
        self.assertTrue(status["available"])
        self.assertEqual(status["dirty"], [])

        result = updates.apply_update_at(self.local)
        self.assertTrue(result["updated"])
        self.assertEqual(updates.current_branch(self.local), "main")
        self.assertEqual(result["sha"], updates.rev_parse(self.local, "origin/main"))
        self.assertEqual((self.local / "README.md").read_text(encoding="utf-8"), "one\n")
        self.assertFalse(updates.dirty_files(self.local))

    def test_dev_update_pins_main_and_discards_dirty_files(self):
        os.environ["VENDOO_STUDIO_DEV"] = "1"
        _git(self.remote, "commit", "--allow-empty", "-m", "second")
        (self.local / "README.md").write_text("local dirt\n", encoding="utf-8")

        status = updates.check_for_updates_at(self.local)
        self.assertTrue(status["available"])
        self.assertIn("README.md", status["dirty"])

        result = updates.apply_update_at(self.local)
        self.assertTrue(result["updated"])
        self.assertEqual(updates.current_branch(self.local), "main")
        self.assertEqual(result["sha"], updates.rev_parse(self.local, "origin/main"))
        self.assertEqual((self.local / "README.md").read_text(encoding="utf-8"), "one\n")
        self.assertFalse(updates.dirty_files(self.local))

    def test_dev_update_pins_main_from_feature_branch(self):
        os.environ["VENDOO_STUDIO_DEV"] = "1"
        _git(self.local, "checkout", "-b", "feature")
        _git(self.local, "commit", "--allow-empty", "-m", "feature work")
        _git(self.remote, "commit", "--allow-empty", "-m", "second")
        (self.local / "README.md").write_text("local dirt\n", encoding="utf-8")

        status = updates.check_for_updates_at(self.local)
        self.assertTrue(status["available"])
        self.assertEqual(status["branch"], "feature")

        result = updates.apply_update_at(self.local)
        self.assertTrue(result["updated"])
        self.assertEqual(updates.current_branch(self.local), "main")
        self.assertEqual(result["sha"], updates.rev_parse(self.local, "origin/main"))
        self.assertFalse(updates.dirty_files(self.local))

    def test_production_fetches_configured_remote_url_not_origin(self):
        github = Path(self.tmp.name) / "github"
        _git(Path(self.tmp.name), "clone", str(self.remote), str(github))
        _git(github, "config", "user.email", "studio@example.com")
        _git(github, "config", "user.name", "Studio")
        _git(github, "commit", "--allow-empty", "-m", "from github")
        os.environ["VENDOO_STUDIO_UPDATE_URL"] = str(github)

        result = updates.apply_update_at(self.local)
        self.assertTrue(result["updated"])
        self.assertEqual(updates.commit_subject(self.local, "HEAD"), "from github")
        self.assertEqual(_git(self.local, "remote", "get-url", "origin"), str(github))


if __name__ == "__main__":
    unittest.main()
