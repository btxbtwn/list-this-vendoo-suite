from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from vendoo_studio.config import BASE_DIR

REMOTE = os.environ.get("VENDOO_STUDIO_UPDATE_REMOTE", "origin")
REF = os.environ.get("VENDOO_STUDIO_UPDATE_REF", "main")
FETCH_TIMEOUT_S = 30
GIT_TIMEOUT_S = 60
BUILD_TIMEOUT_S = 180


class UpdateBlocked(Exception):
    pass


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _run(args: list[str], cwd: Path, timeout: int = GIT_TIMEOUT_S) -> str:
    result = subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_git_env(),
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or f"exit {result.returncode}").strip()
        raise UpdateBlocked(err.splitlines()[-1] if err else f"{args[0]} failed")
    return (result.stdout or "").strip()


def repo_root() -> Path:
    return Path(_run(["git", "rev-parse", "--show-toplevel"], BASE_DIR))


def current_branch(root: Path) -> str:
    return _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], root)


def dirty_files(root: Path) -> list[str]:
    out = _run(["git", "status", "--porcelain"], root)
    if not out:
        return []
    names: list[str] = []
    for line in out.splitlines():
        if not line.strip() or line.startswith("??"):
            continue
        path = line[2:].strip()
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        names.append(path)
    return names


def fetch(root: Path) -> None:
    _run(["git", "fetch", REMOTE, REF], root, timeout=FETCH_TIMEOUT_S)


def rev_parse(root: Path, name: str) -> str:
    return _run(["git", "rev-parse", name], root)


def commit_subject(root: Path, sha: str) -> str:
    return _run(["git", "log", "-1", "--format=%s", sha], root)


def recent_log(root: Path, local: str, remote: str, limit: int = 5) -> list[str]:
    out = _run(["git", "log", "--oneline", f"{local}..{remote}", f"-{limit}"], root)
    return [line for line in out.splitlines() if line.strip()]


def check_for_updates() -> dict:
    try:
        root = repo_root()
    except (UpdateBlocked, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {"available": False, "error": str(exc) or "git is unavailable"}

    try:
        fetch(root)
    except (UpdateBlocked, subprocess.TimeoutExpired) as exc:
        return {
            "available": False,
            "branch": current_branch(root),
            "error": f"Could not fetch {REMOTE}/{REF}: {exc}",
        }

    remote_ref = f"{REMOTE}/{REF}"
    local_sha = rev_parse(root, "HEAD")
    remote_sha = rev_parse(root, remote_ref)
    behind = int(_run(["git", "rev-list", "--count", f"HEAD..{remote_ref}"], root) or "0")
    ahead = int(_run(["git", "rev-list", "--count", f"{remote_ref}..HEAD"], root) or "0")
    log = recent_log(root, "HEAD", remote_ref) if behind else []

    return {
        "available": behind > 0,
        "behind": behind,
        "ahead": ahead,
        "branch": current_branch(root),
        "local_sha": local_sha,
        "remote_sha": remote_sha,
        "remote_ref": remote_ref,
        "summary": commit_subject(root, remote_sha) if behind else "",
        "commits": log,
        "dirty": dirty_files(root),
        "error": None,
    }


def apply_update() -> dict:
    try:
        root = repo_root()
        dirty = dirty_files(root)
        if dirty:
            raise UpdateBlocked("Uncommitted changes. Commit or stash before updating.")

        fetch(root)
        remote_ref = f"{REMOTE}/{REF}"
        behind = int(_run(["git", "rev-list", "--count", f"HEAD..{remote_ref}"], root) or "0")
        if behind == 0:
            return {"ok": True, "updated": False, "sha": rev_parse(root, "HEAD")}

        _run(["git", "merge", "--ff-only", remote_ref], root)
        sha = rev_parse(root, "HEAD")
        rebuilt = _rebuild_frontend_if_needed(root)
        return {"ok": True, "updated": True, "sha": sha, "rebuilt": rebuilt}
    except subprocess.TimeoutExpired as exc:
        raise UpdateBlocked("Timed out talking to git.") from exc


def _rebuild_frontend_if_needed(root: Path) -> bool:
    studio = root / "vendoo-studio"
    dist = studio / "dist"
    if not dist.exists():
        return False
    _run(["npm", "run", "build"], studio, timeout=BUILD_TIMEOUT_S)
    return True


def schedule_restart() -> None:
    if os.environ.get("VENDOO_STUDIO_DEV", "") == "1":
        return

    def _restart() -> None:
        time.sleep(1.0)
        os.execv(sys.executable, [sys.executable, *sys.argv])

    threading.Thread(target=_restart, daemon=True).start()
