from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import httpx

from vendoo_studio.config import APP_NAME, is_frozen, resource_root, user_data_root

GITHUB_API = os.environ.get("VENDOO_STUDIO_GITHUB_API", "https://api.github.com")
GITHUB_REPO = os.environ.get("VENDOO_STUDIO_GITHUB_REPO", "btxbtwn/list-this-vendoo-suite")
RELEASE_TAG = os.environ.get("VENDOO_STUDIO_RELEASE_TAG", "studio-macos")
ZIP_NAME = "List-This-Studio-macos.zip"
INFO_NAME = "build_info.json"
APP_BUNDLE_NAME = f"{APP_NAME}.app"
USER_AGENT = "ListThisStudio/0.1.0"


class PackagedUpdateError(RuntimeError):
    pass


def build_info_path() -> Path:
    override = os.environ.get("VENDOO_STUDIO_BUILD_INFO")
    if override:
        return Path(override).expanduser().resolve()
    return resource_root() / INFO_NAME


def local_build_info() -> dict:
    path = build_info_path()
    if not path.is_file():
        return {"version": "0.1.0", "sha": None, "short_sha": None, "ref": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": "0.1.0", "sha": None, "short_sha": None, "ref": None}
    sha = payload.get("sha")
    return {
        "version": payload.get("version") or "0.1.0",
        "sha": sha,
        "short_sha": payload.get("short_sha") or (sha[:7] if sha else None),
        "ref": payload.get("ref"),
    }


def installed_app_path() -> Path:
    override = os.environ.get("VENDOO_STUDIO_APP_PATH")
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen():
        return Path(sys.executable).resolve().parents[2]
    return Path.home() / "Applications" / APP_BUNDLE_NAME


def _headers() -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    }


def fetch_release(client: httpx.Client | None = None) -> dict:
    url = f"{GITHUB_API.rstrip('/')}/repos/{GITHUB_REPO}/releases/tags/{RELEASE_TAG}"
    own_client = client is None
    http = client or httpx.Client(timeout=30.0, headers=_headers(), follow_redirects=True)
    try:
        response = http.get(url)
        if response.status_code == 404:
            raise PackagedUpdateError("No macOS release has been published yet.")
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise PackagedUpdateError(f"Could not reach GitHub releases: {exc}") from exc
    finally:
        if own_client:
            http.close()


def _asset_map(release: dict) -> dict[str, dict]:
    return {asset.get("name"): asset for asset in release.get("assets") or [] if asset.get("name")}


def _asset_digest(asset: dict | None) -> str | None:
    if not isinstance(asset, dict):
        return None
    digest = str(asset.get("digest") or "").strip()
    if digest.lower().startswith("sha256:"):
        return digest.split(":", 1)[1].strip().lower()
    sha = str(asset.get("sha256") or "").strip().lower()
    return sha or None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_archive_digest(archive: Path, expected: str | None) -> None:
    if not expected:
        raise PackagedUpdateError("The release does not include a SHA-256 digest for the Mac zip.")
    actual = _sha256_file(archive)
    if actual.lower() != expected.lower():
        raise PackagedUpdateError("Downloaded update did not match the signed digest.")


def _verify_app_signature(app_path: Path) -> None:
    if os.environ.get("VENDOO_STUDIO_SKIP_CODESIGN") == "1":
        return
    verify = subprocess.run(
        ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app_path)],
        capture_output=True,
        text=True,
    )
    if verify.returncode != 0:
        raise PackagedUpdateError("The update is not signed by a trusted identity.")


def _validate_zip_members(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            target = (destination / info.filename).resolve()
            if destination != target and not str(target).startswith(str(destination) + os.sep):
                raise PackagedUpdateError("Archive contains an unsafe path.")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise PackagedUpdateError("Archive contains an unsafe symbolic link.")


def _safe_extract_zip(archive: Path, destination: Path) -> None:
    _validate_zip_members(archive, destination)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(destination)


def _download(client: httpx.Client, url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with destination.open("wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)


def remote_build_info(release: dict, client: httpx.Client | None = None) -> dict:
    assets = _asset_map(release)
    info_asset = assets.get(INFO_NAME)
    if info_asset and info_asset.get("browser_download_url"):
        own_client = client is None
        http = client or httpx.Client(timeout=30.0, headers=_headers(), follow_redirects=True)
        try:
            response = http.get(info_asset["browser_download_url"])
            response.raise_for_status()
            payload = response.json()
            sha = payload.get("sha")
            return {
                "version": payload.get("version") or "0.1.0",
                "sha": sha,
                "short_sha": payload.get("short_sha") or (sha[:7] if sha else None),
                "ref": payload.get("ref"),
            }
        finally:
            if own_client:
                http.close()
    sha = release.get("target_commitish")
    if sha and len(str(sha)) >= 7 and all(ch in "0123456789abcdef" for ch in str(sha).lower()[:7]):
        sha = str(sha)
        return {"version": "0.1.0", "sha": sha, "short_sha": sha[:7], "ref": "main"}
    return {"version": "0.1.0", "sha": None, "short_sha": None, "ref": None}


def check_for_packaged_update() -> dict:
    local = local_build_info()
    try:
        release = fetch_release()
        remote = remote_build_info(release)
    except PackagedUpdateError as exc:
        return {
            "available": False,
            "packaged": True,
            "local_sha": local.get("sha"),
            "error": str(exc),
        }
    assets = _asset_map(release)
    zip_asset = assets.get(ZIP_NAME)
    remote_sha = remote.get("sha")
    local_sha = local.get("sha")
    available = bool(zip_asset) and bool(remote_sha) and remote_sha != local_sha
    summary = (release.get("name") or "").strip()
    body = (release.get("body") or "").strip()
    if body:
        summary = f"{summary}\n{body.splitlines()[0]}".strip() if summary else body.splitlines()[0]
    return {
        "available": available,
        "packaged": True,
        "behind": 1 if available else 0,
        "ahead": 0,
        "branch": remote.get("ref") or "main",
        "local_sha": local_sha,
        "remote_sha": remote_sha,
        "remote_ref": f"github:{GITHUB_REPO}:{RELEASE_TAG}",
        "summary": summary,
        "commits": [summary] if summary and available else [],
        "dirty": [],
        "error": None if zip_asset else f"Release {RELEASE_TAG} has no {ZIP_NAME}.",
        "short_sha": remote.get("short_sha"),
        "download_url": (zip_asset or {}).get("browser_download_url"),
        "sha256": _asset_digest(zip_asset),
        "release_url": release.get("html_url"),
    }


def _prepare_app_bundle(app_path: Path, *, clear_quarantine: bool = False) -> None:
    """Restore execute bits. Quarantine is cleared only after signature verification."""
    macos = app_path / "Contents" / "MacOS"
    if macos.is_dir():
        for path in macos.iterdir():
            if path.is_file():
                path.chmod(path.stat().st_mode | 0o111)
    if not clear_quarantine:
        return
    try:
        subprocess.run(
            ["/usr/bin/xattr", "-cr", str(app_path)],
            check=False,
            capture_output=True,
        )
    except FileNotFoundError:
        pass


def _extract_app(archive: Path, destination: Path) -> Path:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    _validate_zip_members(archive, destination)
    try:
        extracted = subprocess.run(
            ["/usr/bin/ditto", "-xk", str(archive), str(destination)],
            capture_output=True,
            text=True,
        )
        ditto_ok = extracted.returncode == 0
    except FileNotFoundError:
        ditto_ok = False
    if not ditto_ok:
        _safe_extract_zip(archive, destination)
    dest = destination.resolve()
    for path in dest.rglob("*"):
        resolved = path.resolve()
        if resolved != dest and not str(resolved).startswith(str(dest) + os.sep):
            raise PackagedUpdateError("Archive contains an unsafe path.")
    matches = [path for path in destination.rglob(APP_BUNDLE_NAME) if path.is_dir()]
    if not matches:
        raise PackagedUpdateError("The downloaded zip did not contain List This Studio.app.")
    app = min(matches, key=lambda path: len(path.parts))
    _prepare_app_bundle(app, clear_quarantine=False)
    return app


def _write_replacer(app_path: Path, new_app: Path, pid: int) -> Path:
    script = user_data_root() / "updates" / "replace-app.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    macos = app_path / "Contents" / "MacOS"
    script.write_text(
        "\n".join(
            [
                "#!/bin/bash",
                "set -euo pipefail",
                f"while /bin/kill -0 {pid} 2>/dev/null; do sleep 0.2; done",
                "sleep 0.4",
                f"/usr/bin/ditto {shlex.quote(str(new_app))} {shlex.quote(str(app_path))}",
                f"/usr/bin/xattr -cr {shlex.quote(str(app_path))} || true",
                f"/bin/chmod -R u+x {shlex.quote(str(macos))} || true",
                f"/usr/bin/open {shlex.quote(str(app_path))}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def apply_packaged_update() -> dict:
    status = check_for_packaged_update()
    if not status.get("available"):
        if status.get("error"):
            raise PackagedUpdateError(status["error"])
        return {"ok": True, "updated": False, "sha": status.get("local_sha"), "packaged": True}
    download_url = status.get("download_url")
    if not download_url:
        raise PackagedUpdateError("The GitHub release does not include a Mac zip.")
    app_path = installed_app_path()
    if not app_path.exists():
        raise PackagedUpdateError(f"Cannot replace {app_path} because that app is missing.")

    staging = Path(tempfile.mkdtemp(prefix="list-this-studio-update-"))
    archive = staging / ZIP_NAME
    with httpx.Client(timeout=120.0, headers=_headers(), follow_redirects=True) as client:
        _download(client, download_url, archive)
    _verify_archive_digest(archive, status.get("sha256"))
    new_app = _extract_app(archive, staging / "unpacked")
    _verify_app_signature(new_app)
    _prepare_app_bundle(new_app, clear_quarantine=True)
    script = _write_replacer(app_path, new_app, os.getpid())
    subprocess.Popen(
        [str(script)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {
        "ok": True,
        "updated": True,
        "sha": status.get("remote_sha"),
        "packaged": True,
        "relaunch": True,
    }
