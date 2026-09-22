"""Read ``CHANGELOG.md`` so the app can show what each version changed.

The repository root file is the single source of truth; the Mac bundle ships a
copy beside ``VERSION``. Entries are parsed rather than rendered whole so the
About panel can mark the version the seller is actually running.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

HEADING = re.compile(
    r"^##\s+(?P<version>\d+\.\d+\.\d+)\s*(?:[—–-]\s*(?P<date>\d{4}-\d{2}-\d{2}))?\s*$"
)


@dataclass(frozen=True)
class ChangelogEntry:
    version: str
    date: str | None
    body: str

    def as_dict(self) -> dict[str, object]:
        return {"version": self.version, "date": self.date, "body": self.body}


def changelog_path() -> Path | None:
    """The first CHANGELOG.md that exists: source checkout, then bundle."""
    candidates: list[Path] = []
    # services → vendoo_studio → server → vendoo-studio → repo root
    candidates.append(Path(__file__).resolve().parents[4] / "CHANGELOG.md")
    try:
        from vendoo_studio.config import resource_root

        candidates.append(resource_root() / "CHANGELOG.md")
    except Exception:
        pass
    for path in candidates:
        if path.is_file():
            return path
    return None


def parse_changelog(text: str) -> list[ChangelogEntry]:
    """Split the file on ``## <version> — <date>`` headings, newest first."""
    entries: list[ChangelogEntry] = []
    version: str | None = None
    date: str | None = None
    lines: list[str] = []

    def flush() -> None:
        if version is None:
            return
        entries.append(ChangelogEntry(version, date, "\n".join(lines).strip()))

    for line in text.splitlines():
        match = HEADING.match(line.strip())
        if match:
            flush()
            version = match.group("version")
            date = match.group("date")
            lines = []
            continue
        if version is not None:
            lines.append(line)
    flush()
    return entries


def changelog_entries() -> list[ChangelogEntry]:
    path = changelog_path()
    if path is None:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return parse_changelog(text)
