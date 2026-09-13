from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlparse

from vendoo_studio.config import extension_source_dir, user_data_root

DEFAULT_VENDOO_URL = "https://web.vendoo.co"
VENDOO_HOSTS = frozenset({"web.vendoo.co", "app.vendoo.co"})

CHROME_CANDIDATES = (
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
    Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
)

EXTENSION_SKIP = {
    ".git",
    ".gitignore",
    ".playwright-mcp",
    "IMPROVEMENTS.md",
    "README.md",
    "TROUBLESHOOTING.md",
    "sample-listing.json",
    "skills",
    "test-script.js",
}


class ChromeBridgeError(RuntimeError):
    pass


def chrome_executable() -> Path | None:
    for candidate in CHROME_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def chrome_profile_dir() -> Path:
    return user_data_root() / "Chrome"


def installed_extension_dir() -> Path:
    return user_data_root() / "vendoo-extension"


def pending_reload_path() -> Path:
    return user_data_root() / "extension-reload-pending"


def _ignored_name(name: str) -> bool:
    return name in EXTENSION_SKIP or name.startswith(".") or name.endswith(".log")


def _ignore_extension(_directory: str, names: list[str]) -> list[str]:
    return [name for name in names if _ignored_name(name)]


def _iter_extension_files(root: Path) -> list[Path]:
    files: list[Path] = []
    if not root.is_dir():
        return files
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(_ignored_name(part) for part in rel_parts):
            continue
        files.append(path)
    return files


def extension_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for path in _iter_extension_files(root):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _overlay_copy(source: Path, destination: Path) -> None:
    wanted: set[str] = set()
    for path in _iter_extension_files(source):
        rel = path.relative_to(source)
        wanted.add(rel.as_posix())
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    for path in _iter_extension_files(destination):
        rel = path.relative_to(destination).as_posix()
        if rel not in wanted:
            path.unlink(missing_ok=True)
    for directory in sorted(
        (p for p in destination.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        try:
            next(directory.iterdir())
        except StopIteration:
            directory.rmdir()
        except OSError:
            pass


def install_bundled_extension() -> bool:
    """Copy the bundled extension into Chrome's load path. True when files changed."""
    source = extension_source_dir()
    if not (source / "manifest.json").is_file():
        raise ChromeBridgeError(
            "The Vendoo Chrome extension is missing from this app. Re-download List This Studio."
        )
    destination = installed_extension_dir()
    destination.parent.mkdir(parents=True, exist_ok=True)
    new_fingerprint = extension_fingerprint(source)
    old_fingerprint = extension_fingerprint(destination) if destination.exists() else None
    if old_fingerprint == new_fingerprint:
        return False

    staging = destination.parent / f".{destination.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(source, staging, ignore=_ignore_extension)
    if destination.exists():
        _overlay_copy(staging, destination)
        shutil.rmtree(staging)
    else:
        staging.rename(destination)
    return True


def sync_bundled_extension() -> Path:
    install_bundled_extension()
    return installed_extension_dir()


def mark_extension_reload_pending() -> str:
    token = uuid.uuid4().hex
    path = pending_reload_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")
    return token


def pending_extension_reload_token() -> str | None:
    try:
        token = pending_reload_path().read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return token or None


def clear_extension_reload_pending() -> None:
    pending_reload_path().unlink(missing_ok=True)


def needs_worker_reload(pending: str | None, reported: str | None, files_changed: bool) -> bool:
    if files_changed:
        return True
    return bool(pending) and pending != reported


def bundled_extension_version() -> str | None:
    path = extension_source_dir() / "manifest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    version = payload.get("version")
    if version is None:
        return None
    text = str(version).strip()
    return text or None


def extension_files_in_sync() -> bool:
    source = extension_source_dir()
    if not (source / "manifest.json").is_file():
        return False
    destination = installed_extension_dir()
    if not destination.is_dir():
        return True
    return extension_fingerprint(source) == extension_fingerprint(destination)


def extension_build_status(
    reported_version: str | None,
    reported_generation: str | None,
) -> dict:
    expected_version = bundled_extension_version()
    files_in_sync = extension_files_in_sync()
    pending = pending_extension_reload_token()
    reload_pending = needs_worker_reload(pending, reported_generation, not files_in_sync)
    version_mismatch = bool(
        reported_version and expected_version and reported_version != expected_version
    )
    return {
        "expected_version": expected_version,
        "version": reported_version,
        "up_to_date": (not reload_pending) and (not version_mismatch),
        "reload_pending": reload_pending,
        "files_in_sync": files_in_sync,
    }


def is_vendoo_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme == "https" and parsed.hostname in VENDOO_HOSTS


def listing_url_for_job(item_id: str | None = None, url: str | None = None) -> str | None:
    raw = str(url or "").strip()
    if raw and is_vendoo_url(raw):
        return raw
    item = str(item_id or "").strip()
    if item and item != "new" and all(ch.isalnum() or ch in "-_" for ch in item):
        return f"https://web.vendoo.co/app/item/{item}"
    return None


def launch_args(
    executable: Path,
    extension_dir: Path,
    profile_dir: Path,
    url: str = DEFAULT_VENDOO_URL,
) -> list[str]:
    target = url if is_vendoo_url(url) else DEFAULT_VENDOO_URL
    return [
        str(executable),
        f"--user-data-dir={profile_dir}",
        "--disable-features=DisableLoadExtensionCommandLineSwitch,CalculateNativeWinOcclusion",
        f"--load-extension={extension_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
        target,
    ]


def launch_studio_chrome(url: str = DEFAULT_VENDOO_URL) -> dict:
    target = str(url or "").strip() or DEFAULT_VENDOO_URL
    if not is_vendoo_url(target):
        raise ChromeBridgeError("That is not a Vendoo listing URL.")
    executable = chrome_executable()
    if executable is None:
        raise ChromeBridgeError(
            "Google Chrome is not installed. Install it from https://www.google.com/chrome, then click Connect Chrome again."
        )
    extension_dir = sync_bundled_extension()
    profile_dir = chrome_profile_dir()
    profile_dir.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        launch_args(executable, extension_dir, profile_dir, target),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {
        "ok": True,
        "browser": executable.parent.parent.parent.stem,
        "extension_dir": str(extension_dir),
        "profile_dir": str(profile_dir),
    }
