from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from vendoo_studio.config import BASE_DIR, is_packaged

REMOTE = os.environ.get("VENDOO_STUDIO_UPDATE_REMOTE", "origin")
REF = os.environ.get("VENDOO_STUDIO_UPDATE_REF", "main")
DEFAULT_REMOTE_URL = "https://github.com/btxbtwn/list-this-vendoo-suite.git"
FETCH_TIMEOUT_S = 30
GIT_TIMEOUT_S = 60
BUILD_TIMEOUT_S = 180
CLONE_TIMEOUT_S = 180
INSTALL_PRESERVE = (
    "vendoo-studio/data",
    "vendoo-studio/.venv",
    "vendoo-studio/dist",
    "vendoo-studio/server/vendoo_studio/desktop.py",
)


class UpdateBlocked(Exception):
    pass


def _is_dev() -> bool:
    return os.environ.get("VENDOO_STUDIO_DEV", "") == "1"


def remote_url() -> str:
    return os.environ.get("VENDOO_STUDIO_UPDATE_URL", DEFAULT_REMOTE_URL)


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


def is_linked_worktree(root: Path) -> bool:
    return (root / ".git").is_file()


def _normalize_git_url(url: str) -> str:
    return url.strip().rstrip("/").removesuffix(".git")


def _ensure_origin_url(root: Path) -> None:
    url = remote_url()
    try:
        current = _run(["git", "remote", "get-url", "origin"], root)
    except UpdateBlocked:
        _run(["git", "remote", "add", "origin", url], root)
        return
    if _normalize_git_url(current) != _normalize_git_url(url):
        _run(["git", "remote", "set-url", "origin", url], root)


def fetch(root: Path) -> None:
    if _is_dev():
        _run(["git", "fetch", REMOTE, REF], root, timeout=FETCH_TIMEOUT_S)
        return
    _ensure_origin_url(root)
    _run(
        ["git", "fetch", remote_url(), f"{REF}:refs/remotes/{REMOTE}/{REF}"],
        root,
        timeout=FETCH_TIMEOUT_S,
    )


def rev_parse(root: Path, name: str) -> str:
    return _run(["git", "rev-parse", name], root)


def commit_subject(root: Path, sha: str) -> str:
    return _run(["git", "log", "-1", "--format=%s", sha], root)


def recent_log(root: Path, local: str, remote: str, limit: int = 5) -> list[str]:
    out = _run(["git", "log", "--oneline", f"{local}..{remote}", f"-{limit}"], root)
    return [line for line in out.splitlines() if line.strip()]


def _remote_ref() -> str:
    return f"{REMOTE}/{REF}"


def _in_sync_with_remote(root: Path, remote_ref: str) -> bool:
    return current_branch(root) == REF and rev_parse(root, "HEAD") == rev_parse(root, remote_ref)


def pin_to_remote(root: Path, remote_ref: str) -> None:
    _run(["git", "checkout", "--force", "-B", REF, remote_ref], root)


def _copy_preserved(src_root: Path, dest_root: Path) -> None:
    for rel in INSTALL_PRESERVE:
        src = src_root / rel
        dest = dest_root / rel
        if not src.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest, symlinks=True)
        else:
            shutil.copy2(src, dest)


def ensure_standalone_clone(root: Path) -> Path:
    """Replace a linked git worktree with an independent clone of the GitHub repo."""
    if _is_dev() or not is_linked_worktree(root):
        if not _is_dev():
            _ensure_origin_url(root)
        return root

    parent = root.parent
    staging = parent / f".{root.name}.remote-clone"
    backup = parent / f".{root.name}.worktree-old"
    if staging.exists():
        shutil.rmtree(staging)
    _run(
        ["git", "clone", "--branch", REF, "--single-branch", remote_url(), str(staging)],
        parent,
        timeout=CLONE_TIMEOUT_S,
    )
    _copy_preserved(root, staging)
    if backup.exists():
        shutil.rmtree(backup)
    root.rename(backup)
    staging.rename(root)
    try:
        _run(["git", "worktree", "prune"], backup)
    except UpdateBlocked:
        pass
    return root


def check_for_updates() -> dict:
    if is_packaged():
        from vendoo_studio.services.packaged_updates import PackagedUpdateError, check_for_packaged_update

        try:
            return check_for_packaged_update()
        except PackagedUpdateError as exc:
            return {"available": False, "packaged": True, "error": str(exc)}
    try:
        return check_for_updates_at(repo_root())
    except (UpdateBlocked, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {"available": False, "error": str(exc) or "git is unavailable"}


def check_for_updates_at(root: Path) -> dict:
    try:
        fetch(root)
    except (UpdateBlocked, subprocess.TimeoutExpired) as exc:
        return {
            "available": False,
            "branch": current_branch(root),
            "error": f"Could not fetch {remote_url()} {REF}: {exc}",
        }

    remote_ref = _remote_ref()
    local_sha = rev_parse(root, "HEAD")
    remote_sha = rev_parse(root, remote_ref)
    behind = int(_run(["git", "rev-list", "--count", f"HEAD..{remote_ref}"], root) or "0")
    ahead = int(_run(["git", "rev-list", "--count", f"{remote_ref}..HEAD"], root) or "0")
    on_ref = current_branch(root) == REF
    available = not _in_sync_with_remote(root, remote_ref)
    log = recent_log(root, "HEAD", remote_ref) if behind else []

    return {
        "available": available,
        "behind": behind,
        "ahead": ahead,
        "branch": current_branch(root),
        "local_sha": local_sha,
        "remote_sha": remote_sha,
        "remote_ref": remote_ref,
        "summary": commit_subject(root, remote_sha) if available else "",
        "commits": log,
        "dirty": dirty_files(root) if _is_dev() else [],
        "error": None,
        "on_ref": on_ref,
        "remote_url": remote_url() if not _is_dev() else None,
    }


def apply_update() -> dict:
    if is_packaged():
        from vendoo_studio.services.packaged_updates import PackagedUpdateError, apply_packaged_update

        try:
            return apply_packaged_update()
        except PackagedUpdateError as exc:
            raise UpdateBlocked(str(exc)) from exc
    try:
        return apply_update_at(repo_root())
    except subprocess.TimeoutExpired as exc:
        raise UpdateBlocked("Timed out talking to git.") from exc


def reinstall_app() -> dict:
    if not is_packaged():
        raise UpdateBlocked("Reinstall is only available in the Mac app.")
    from vendoo_studio.services.packaged_updates import PackagedUpdateError, reinstall_packaged_app

    try:
        return reinstall_packaged_app()
    except PackagedUpdateError as exc:
        raise UpdateBlocked(str(exc)) from exc


def apply_update_at(root: Path) -> dict:
    if not _is_dev():
        root = ensure_standalone_clone(root)
    fetch(root)
    remote_ref = _remote_ref()
    if _in_sync_with_remote(root, remote_ref):
        return {"ok": True, "updated": False, "sha": rev_parse(root, "HEAD")}
    pin_to_remote(root, remote_ref)
    sha = rev_parse(root, "HEAD")
    rebuilt = _rebuild_frontend_if_needed(root)
    return {"ok": True, "updated": True, "sha": sha, "rebuilt": rebuilt}


def _rebuild_frontend_if_needed(root: Path) -> bool:
    studio = root / "vendoo-studio"
    dist = studio / "dist"
    if not dist.exists():
        return False
    _run(["npm", "run", "build"], studio, timeout=BUILD_TIMEOUT_S)
    return True


def schedule_restart() -> None:
    if _is_dev() and not is_packaged():
        return

    def _restart() -> None:
        time.sleep(1.0)
        if is_packaged():
            os._exit(0)
        os.execv(sys.executable, [sys.executable, *sys.argv])

    threading.Thread(target=_restart, daemon=True).start()
