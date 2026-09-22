#!/usr/bin/env python3
"""Fail when CHANGELOG.md does not describe the version Studio is shipping.

Two rules, both aimed at the same failure: a version bump that nobody wrote
down, leaving About → What's new silent about the build sellers install.

1. Always: the newest entry is for the current ``VERSION``, has notes, and the
   file stays a strictly descending list of unique versions.
2. With ``--base <ref>``: if this branch bumps ``VERSION``, the new version has
   to be an entry the base ref did not already have.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHANGELOG = ROOT / "CHANGELOG.md"
VERSION_FILE = ROOT / "vendoo-studio" / "VERSION"

HEADING = re.compile(
    r"^##\s+(?P<version>\d+\.\d+\.\d+)\s*(?:[—–-]\s*(?P<date>\d{4}-\d{2}-\d{2}))?\s*$"
)


def parse(text: str) -> list[tuple[str, str]]:
    """``[(version, body)]`` in file order. Mirrors services/changelog.py."""
    entries: list[tuple[str, str]] = []
    version: str | None = None
    lines: list[str] = []
    for line in text.splitlines():
        match = HEADING.match(line.strip())
        if match:
            if version is not None:
                entries.append((version, "\n".join(lines).strip()))
            version = match.group("version")
            lines = []
            continue
        if version is not None:
            lines.append(line)
    if version is not None:
        entries.append((version, "\n".join(lines).strip()))
    return entries


def git_show(ref: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{ref}:{path}"],
        capture_output=True,
        text=True,
    )
    return result.stdout if result.returncode == 0 else None


def fail(message: str) -> None:
    raise SystemExit(f"CHANGELOG.md: {message}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="Base ref to compare against (a PR's target branch).")
    args = parser.parse_args()

    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    entries = parse(CHANGELOG.read_text(encoding="utf-8"))
    if not entries:
        fail("no version entries found. Use '## <version> — <YYYY-MM-DD>' headings.")

    newest, body = entries[0]
    if newest != version:
        fail(
            f"the newest entry is {newest}, but Studio is on {version}.\n"
            f"Add a '## {version} — <YYYY-MM-DD>' section at the top describing the change."
        )
    if not body:
        fail(f"the {version} entry has no notes. Say what changed, in the seller's words.")

    versions = [entry[0] for entry in entries]
    duplicates = {item for item in versions if versions.count(item) > 1}
    if duplicates:
        fail(f"duplicate entries for {', '.join(sorted(duplicates))}.")

    parsed = [tuple(int(part) for part in item.split(".")) for item in versions]
    if parsed != sorted(parsed, reverse=True):
        fail("entries must be newest first.")

    if args.base:
        base_version = (git_show(args.base, "vendoo-studio/VERSION") or "").strip()
        if base_version and base_version != version:
            base_entries = dict(parse(git_show(args.base, "CHANGELOG.md") or ""))
            if version in base_entries:
                fail(
                    f"{version} was already on {args.base}, so this bump added no entry.\n"
                    "Every version bump needs its own section."
                )
            print(f"Version bump {base_version} → {version} brings a new changelog entry.")

    print(f"CHANGELOG.md documents {version} ({len(entries)} entries).")


if __name__ == "__main__":
    sys.exit(main())
