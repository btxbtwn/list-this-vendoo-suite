"""What's new: the parsed CHANGELOG.md, tagged with the running version."""

from __future__ import annotations

from fastapi import APIRouter

from vendoo_studio.services.changelog import changelog_entries
from vendoo_studio.version import app_version

router = APIRouter(prefix="/api/changelog", tags=["changelog"])


@router.get("")
def get_changelog():
    entries = changelog_entries()
    return {
        "version": app_version(),
        "entries": [entry.as_dict() for entry in entries],
    }
