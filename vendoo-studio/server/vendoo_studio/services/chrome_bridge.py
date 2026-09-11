from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from vendoo_studio.config import extension_source_dir, user_data_root

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


def _ignore_extension(_directory: str, names: list[str]) -> list[str]:
    ignored = []
    for name in names:
        if name in EXTENSION_SKIP or name.startswith(".") or name.endswith(".log"):
            ignored.append(name)
    return ignored


def sync_bundled_extension() -> Path:
    source = extension_source_dir()
    if not (source / "manifest.json").is_file():
        raise ChromeBridgeError(
            "The Vendoo Chrome extension is missing from this app. Re-download List This Studio."
        )
    destination = installed_extension_dir()
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=_ignore_extension)
    return destination


def launch_args(executable: Path, extension_dir: Path, profile_dir: Path) -> list[str]:
    return [
        str(executable),
        f"--user-data-dir={profile_dir}",
        "--disable-features=DisableLoadExtensionCommandLineSwitch",
        f"--load-extension={extension_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "https://web.vendoo.co",
    ]


def launch_studio_chrome() -> dict:
    executable = chrome_executable()
    if executable is None:
        raise ChromeBridgeError(
            "Google Chrome is not installed. Install it from https://www.google.com/chrome, then click Connect Chrome again."
        )
    extension_dir = sync_bundled_extension()
    profile_dir = chrome_profile_dir()
    profile_dir.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        launch_args(executable, extension_dir, profile_dir),
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
