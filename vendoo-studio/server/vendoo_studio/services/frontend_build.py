"""Tell whether ``dist/`` matches the checkout it is being served from.

The backend reads its version from the ``VERSION`` file, while the UI is a
separate build artifact. An update that moved the source but did not rebuild the
bundle used to be undetectable: the status bar showed the new version because it
asked the backend, and every pixel around it came from the old build. The build
stamp written by ``vite.config.ts`` closes that gap.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from vendoo_studio.config import frontend_dist_dir
from vendoo_studio.version import app_version

STAMP_NAME = "build-stamp.json"
GIT_TIMEOUT_S = 10

log = logging.getLogger("vendoo_studio.frontend_build")


def stamp_path() -> Path:
    return frontend_dist_dir() / STAMP_NAME


def dist_stamp() -> dict | None:
    """The stamp vite wrote into ``dist/``, or None when it is absent/corrupt."""
    try:
        payload = json.loads(stamp_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _git(args: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip()


def head_sha() -> str | None:
    return _git(["rev-parse", "HEAD"], frontend_dist_dir().parent) or None


def _tree_is_dirty() -> bool:
    # A dev with edits in flight is expected to be out of step with dist/; they
    # run the vite dev server. Only hold a clean checkout to its commit.
    out = _git(["status", "--porcelain"], frontend_dist_dir().parent)
    return bool(out)


def frontend_needs_build() -> str | None:
    """A human-readable reason the bundle must be rebuilt, or None if it is current."""
    if not (frontend_dist_dir() / "index.html").is_file():
        return "the interface has not been built yet"

    stamp = dist_stamp()
    if stamp is None:
        return "the built interface carries no build stamp"

    version = app_version()
    built = str(stamp.get("version") or "").strip()
    if built != version:
        return f"the built interface is {built or 'unknown'} but Studio is {version}"

    sha = head_sha()
    built_sha = str(stamp.get("sha") or "").strip()
    if sha and built_sha and sha != built_sha and not _tree_is_dirty():
        return f"the built interface is commit {built_sha[:7]} but the checkout is {sha[:7]}"
    return None
