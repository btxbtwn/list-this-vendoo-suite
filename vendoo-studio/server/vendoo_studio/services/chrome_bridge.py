from __future__ import annotations

import hashlib
import json
import os
import signal
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from vendoo_studio.config import extension_source_dir, user_data_root

DEFAULT_VENDOO_URL = "https://web.vendoo.co/app"
VENDOO_HOSTS = frozenset({"web.vendoo.co", "app.vendoo.co"})

CHROME_APP_BINARIES = (
    Path("Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("Chromium.app/Contents/MacOS/Chromium"),
    Path("Brave Browser.app/Contents/MacOS/Brave Browser"),
    Path("Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
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


def chrome_search_dirs() -> tuple[Path, ...]:
    return (Path("/Applications"), Path.home() / "Applications")


def chrome_executable() -> Path | None:
    for root in chrome_search_dirs():
        for relative in CHROME_APP_BINARIES:
            candidate = root / relative
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
    *,
    visible: bool = False,
) -> list[str]:
    args = [
        str(executable),
        f"--user-data-dir={profile_dir}",
        "--disable-features=DisableLoadExtensionCommandLineSwitch,CalculateNativeWinOcclusion",
        f"--disable-extensions-except={extension_dir}",
        f"--load-extension={extension_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
    ]
    if visible:
        args.extend(
            [
                "--new-window",
                "--window-position=80,80",
                "--window-size=1280,900",
                url if is_vendoo_url(url) else DEFAULT_VENDOO_URL,
            ]
        )
    else:
        args.append("--no-startup-window")
    return args


def launch_studio_chrome(url: str = DEFAULT_VENDOO_URL, *, visible: bool = False) -> dict:
    target = str(url or "").strip() or DEFAULT_VENDOO_URL
    if not is_vendoo_url(target):
        raise ChromeBridgeError("That is not a Vendoo listing URL.")
    executable = chrome_executable()
    if executable is None:
        raise ChromeBridgeError(
            "Google Chrome is not installed. Install it from https://www.google.com/chrome, then click Connect Chrome again."
        )
    extension_dir = sync_bundled_extension()
    profile_dir = chrome_profile_dir().resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    args = launch_args(executable, extension_dir, profile_dir, target, visible=visible)
    if sys.platform == "darwin":
        app = executable.parent.parent.parent
        subprocess.Popen(
            ["open", "-na", str(app), "--args", *args[1:]],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    else:
        subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    return {
        "ok": True,
        "browser": executable.parent.parent.parent.stem,
        "extension_dir": str(extension_dir),
        "profile_dir": str(profile_dir),
        "visible": visible,
    }


def studio_chrome_profile_markers() -> tuple[str, ...]:
    markers = []
    for root in (chrome_profile_dir(), installed_extension_dir()):
        for path in (root, root.resolve()):
            text = str(path)
            if not text:
                continue
            markers.append(f"--user-data-dir={text}")
            markers.append(f'--user-data-dir="{text}"')
            markers.append(f"--load-extension={text}")
            markers.append(f'--load-extension="{text}"')
    return tuple(dict.fromkeys(markers))


def studio_chrome_pids() -> list[int]:
    """PIDs for the Studio-managed Chrome profile only, never the user's main Chrome."""
    markers = studio_chrome_profile_markers()
    try:
        output = subprocess.check_output(["ps", "-axww", "-o", "pid=,command="], text=True)
    except (OSError, subprocess.CalledProcessError):
        return []
    pids: list[int] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not any(marker in line for marker in markers):
            continue
        pid_s = line.split(None, 1)[0]
        try:
            pids.append(int(pid_s))
        except ValueError:
            continue
    return pids


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


CHROME_LOCK_NAMES = ("SingletonLock", "SingletonSocket", "SingletonCookie")


def clear_chrome_profile_locks() -> None:
    root = chrome_profile_dir().resolve()
    if not root.is_dir():
        return
    for name in CHROME_LOCK_NAMES:
        path = root / name
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            elif path.exists() or path.is_symlink():
                path.unlink()
        except OSError:
            pass


def quit_studio_chrome(timeout_sec: float = 5.0) -> None:
    pids = set(studio_chrome_pids())
    if not pids:
        clear_chrome_profile_locks()
        return
    for pid in list(pids):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pids.discard(pid)
        except PermissionError:
            pass
    deadline = time.monotonic() + timeout_sec
    while pids and time.monotonic() < deadline:
        pids = {pid for pid in pids if _pid_is_running(pid)}
        if pids:
            time.sleep(0.1)
    for pid in studio_chrome_pids():
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    leftover_deadline = time.monotonic() + 1.0
    while studio_chrome_pids() and time.monotonic() < leftover_deadline:
        time.sleep(0.05)
    leftovers = studio_chrome_pids()
    if leftovers:
        for marker in studio_chrome_profile_markers():
            subprocess.run(
                ["pkill", "-f", marker],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    if not studio_chrome_pids():
        clear_chrome_profile_locks()


def relaunch_studio_chrome(url: str = DEFAULT_VENDOO_URL, *, visible: bool = True) -> dict:
    """Replace the Studio Chrome process so --load-extension re-reads current files."""
    sync_bundled_extension()
    clear_extension_reload_pending()
    quit_studio_chrome()
    return launch_studio_chrome(url, visible=visible)
