from __future__ import annotations

import unittest
from pathlib import Path

from vendoo_studio.services.changelog import (
    changelog_entries,
    changelog_path,
    parse_changelog,
)
from vendoo_studio.version import app_version

STUDIO_DIR = Path(__file__).resolve().parents[2]


class ParseChangelogTest(unittest.TestCase):
    def test_reads_version_date_and_body(self) -> None:
        entries = parse_changelog(
            "# Changelog\n"
            "\n"
            "Preamble that belongs to no version.\n"
            "\n"
            "## 0.2.0 — 2026-09-22\n"
            "\n"
            "- Newest change\n"
            "\n"
            "## 0.1.9 — 2026-09-18\n"
            "\n"
            "- Older change\n"
            "- Second bullet\n"
        )
        self.assertEqual([entry.version for entry in entries], ["0.2.0", "0.1.9"])
        self.assertEqual(entries[0].date, "2026-09-22")
        self.assertEqual(entries[0].body, "- Newest change")
        self.assertEqual(entries[1].body, "- Older change\n- Second bullet")

    def test_date_is_optional(self) -> None:
        entries = parse_changelog("## 1.0.0\n\n- Shipped\n")
        self.assertEqual(entries[0].date, None)
        self.assertEqual(entries[0].body, "- Shipped")

    def test_ignores_other_headings(self) -> None:
        entries = parse_changelog("## Unreleased\n\n- Nothing yet\n\n## 0.1.1 — 2026-01-02\n\n- Real\n")
        self.assertEqual([entry.version for entry in entries], ["0.1.1"])


class RepositoryChangelogTest(unittest.TestCase):
    """The shipped file has to stay parseable and current, or About lies."""

    def test_file_is_found_and_parses(self) -> None:
        path = changelog_path()
        self.assertIsNotNone(path)
        self.assertTrue(Path(str(path)).is_file())
        entries = changelog_entries()
        self.assertTrue(entries)
        for entry in entries:
            self.assertTrue(entry.body.strip(), f"{entry.version} has no notes")

    def test_newest_entry_matches_the_studio_version(self) -> None:
        version = (STUDIO_DIR / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(changelog_entries()[0].version, version)
        self.assertEqual(app_version(), version)

    def test_versions_are_unique_and_descending(self) -> None:
        versions = [entry.version for entry in changelog_entries()]
        self.assertEqual(len(versions), len(set(versions)))
        parsed = [tuple(int(part) for part in version.split(".")) for version in versions]
        self.assertEqual(parsed, sorted(parsed, reverse=True))
