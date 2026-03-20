#!/usr/bin/env python3
"""
Portable Chrome DevTools MCP bootstrap/runtime helper for raghouse-box-sourcing.

This wrapper avoids checkout-specific config paths by:
- verifying local prerequisites
- prefetching `mcporter` and `chrome-devtools-mcp` with `npx`
- proxying ad-hoc `mcporter list|call|auth` commands against a repo-local
  Chrome DevTools MCP runtime
- optionally launching a dedicated Chrome remote-debugging session with a
  repo-local profile pointed at Raghouse
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from urllib import error, request


SCRIPT_PATH = Path(__file__).resolve()
SKILL_DIR = SCRIPT_PATH.parent.parent
DATA_DIR = SKILL_DIR / "data"
RUNTIME_DIR = DATA_DIR / "runtime"
MCPORTER_CONFIG_PATH = RUNTIME_DIR / "mcporter.json"
DEFAULT_REMOTE_DEBUGGING_PORT = 9222
DEFAULT_RAGHOUSE_URL = "https://raghouse.com/collections/all"
SERVER_NAME = "chrome-devtools"
MIN_NODE_VERSION = (20, 19, 0)


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def portable_path(path: Path) -> str:
    return os.path.relpath(path, SKILL_DIR).replace(os.sep, "/")


def print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def fail(message: str) -> int:
    print(f"Error: {message}", file=sys.stderr)
    return 1


def detect_command_path(command: str) -> str | None:
    return shutil.which(command)


def parse_node_version(raw_version: str) -> tuple[int, int, int]:
    value = clean_text(raw_version).lstrip("v")
    parts = value.split(".")
    numeric = []
    for part in parts[:3]:
        digits = "".join(char for char in part if char.isdigit())
        numeric.append(int(digits or "0"))
    while len(numeric) < 3:
        numeric.append(0)
    return tuple(numeric[:3])


def version_string(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def run_command(
    command: list[str],
    *,
    check: bool = False,
    capture_output: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=check,
        capture_output=capture_output,
        text=text,
    )


def ensure_node_runtime() -> dict[str, object]:
    node_path = detect_command_path("node")
    npx_path = detect_command_path("npx")
    if not node_path or not npx_path:
        missing = []
        if not node_path:
            missing.append("node")
        if not npx_path:
            missing.append("npx")
        raise RuntimeError(
            "Missing required command(s): "
            + ", ".join(missing)
            + ". Install Node.js v20.19+ so both `node` and `npx` are available."
        )

    node_version_result = run_command(["node", "--version"], check=True)
    node_version_text = clean_text(node_version_result.stdout or node_version_result.stderr)
    node_version = parse_node_version(node_version_text)
    if node_version < MIN_NODE_VERSION:
        raise RuntimeError(
            f"Node.js {version_string(node_version)} is too old. Install Node.js {version_string(MIN_NODE_VERSION)} or newer."
        )

    return {
        "node_path": node_path,
        "npx_path": npx_path,
        "node_version": version_string(node_version),
    }


def env_or_default(name: str, default: str) -> str:
    value = clean_text(os.environ.get(name))
    return value or default


def mcporter_base_command(config_path: Path) -> list[str]:
    return ["npx", "-y", "mcporter@latest", "--config", str(config_path)]


def browser_url_candidates() -> list[str]:
    explicit = clean_text(
        os.environ.get("RAGHOUSE_BOX_SOURCING_BROWSER_URL") or os.environ.get("CHROME_DEVTOOLS_BROWSER_URL")
    )
    port = env_or_default("RAGHOUSE_BOX_SOURCING_CHROME_DEBUG_PORT", str(DEFAULT_REMOTE_DEBUGGING_PORT))
    defaults = [f"http://127.0.0.1:{port}", f"http://localhost:{port}"]
    if explicit:
        return [explicit, *[item for item in defaults if item != explicit]]
    return defaults


def browser_url_is_reachable(browser_url: str) -> bool:
    version_url = browser_url.rstrip("/") + "/json/version"
    try:
        with request.urlopen(version_url, timeout=2) as response:
            return 200 <= response.status < 300
    except (error.URLError, TimeoutError, ValueError):
        return False


def first_reachable_browser_url() -> str | None:
    for candidate in browser_url_candidates():
        if browser_url_is_reachable(candidate):
            return candidate
    return None


def chrome_devtools_server_command() -> tuple[list[str], str]:
    command = ["npx", "-y", "chrome-devtools-mcp@latest", "--no-usage-statistics"]
    reachable_browser_url = first_reachable_browser_url()
    if reachable_browser_url:
        command.append(f"--browser-url={reachable_browser_url}")
        connection_mode = "browser-url"
    else:
        command.append("--autoConnect")
        connection_mode = "auto-connect"

    if env_or_default("RAGHOUSE_BOX_SOURCING_HEADLESS", "0") in {"1", "true", "yes"}:
        command.append("--headless")

    return command, connection_mode


def write_mcporter_config(server_command: list[str]) -> tuple[Path, bool]:
    config_path = MCPORTER_CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "mcpServers": {
            SERVER_NAME: {
                "command": server_command[0],
                "args": server_command[1:],
                "description": "Chrome DevTools MCP for Raghouse",
            }
        },
        "imports": [],
    }

    existing_payload = None
    if config_path.exists():
        try:
            existing_payload = json.loads(config_path.read_text())
        except json.JSONDecodeError:
            existing_payload = None

    updated = existing_payload != payload
    if updated:
        config_path.write_text(json.dumps(payload, indent=2) + "\n")

    return config_path, updated


def ensure_mcporter_daemon(config_path: Path) -> dict[str, object]:
    result = run_command([*mcporter_base_command(config_path), "daemon", "start"])
    success = result.returncode == 0
    return {
        "command": [*mcporter_base_command(config_path), "daemon", "start"],
        "success": success,
        "stdout": clean_text(result.stdout),
        "stderr": clean_text(result.stderr),
    }


def prefetch_npx_package(command: list[str]) -> dict[str, object]:
    result = run_command(command)
    success = result.returncode == 0
    return {
        "command": command,
        "success": success,
        "stdout": clean_text(result.stdout),
        "stderr": clean_text(result.stderr),
    }


def common_chrome_candidates() -> list[Path]:
    home = Path.home()
    system = platform.system()
    candidates: list[Path] = []

    explicit = clean_text(
        os.environ.get("RAGHOUSE_BOX_SOURCING_CHROME_PATH")
        or os.environ.get("CHROME_PATH")
        or os.environ.get("GOOGLE_CHROME_BIN")
    )
    if explicit:
        candidates.append(Path(explicit))

    if system == "Darwin":
        candidates.extend(
            [
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                home / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                Path("/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary"),
            ]
        )
    elif system == "Windows":
        roots = [
            Path(os.environ.get("PROGRAMFILES", "")),
            Path(os.environ.get("PROGRAMFILES(X86)", "")),
            Path(os.environ.get("LOCALAPPDATA", "")),
        ]
        for root in roots:
            if not str(root):
                continue
            candidates.extend(
                [
                    root / "Google/Chrome/Application/chrome.exe",
                    root / "Chromium/Application/chrome.exe",
                ]
            )
    else:
        for command_name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            resolved = detect_command_path(command_name)
            if resolved:
                candidates.append(Path(resolved))

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            deduped.append(candidate)
            seen.add(key)
    return deduped


def find_chrome_binary() -> Path | None:
    for candidate in common_chrome_candidates():
        if candidate.exists():
            return candidate
    return None


def launch_chrome(port: int, url: str | None) -> dict[str, object]:
    chrome_binary = find_chrome_binary()
    if chrome_binary is None:
        raise RuntimeError(
            "Could not find a Chrome binary automatically. Set RAGHOUSE_BOX_SOURCING_CHROME_PATH or CHROME_PATH first."
        )

    profile_dir = RUNTIME_DIR / "chrome-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    command = [
        str(chrome_binary),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if url:
        command.append(url)

    popen_kwargs: dict[str, object] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        popen_kwargs["start_new_session"] = True

    process = subprocess.Popen(command, **popen_kwargs)
    return {
        "pid": process.pid,
        "chrome_path": str(chrome_binary),
        "browser_url": f"http://127.0.0.1:{port}",
        "profile_dir": portable_path(profile_dir),
        "launch_command": command,
    }


def cmd_bootstrap(_: argparse.Namespace) -> int:
    try:
        runtime = ensure_node_runtime()
    except RuntimeError as exc:
        return fail(str(exc))

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    mcporter_prefetch = prefetch_npx_package(["npx", "-y", "mcporter@latest", "--help"])
    chrome_prefetch = prefetch_npx_package(["npx", "-y", "chrome-devtools-mcp@latest", "--help"])
    chrome_binary = find_chrome_binary()
    browser_url = first_reachable_browser_url()
    server_command, connection_mode = chrome_devtools_server_command()
    config_path, config_updated = write_mcporter_config(server_command)
    daemon_status = ensure_mcporter_daemon(config_path)

    print_json(
        {
            "chrome_binary": str(chrome_binary) if chrome_binary else None,
            "connection_mode": connection_mode,
            "config_path": portable_path(config_path),
            "config_updated": config_updated,
            "daemon": daemon_status,
            "detected_browser_url": browser_url,
            "downloads": {
                "chrome_devtools_mcp": chrome_prefetch,
                "mcporter": mcporter_prefetch,
            },
            "next_steps": {
                "bootstrap": "python3 scripts/devtools_runtime.py bootstrap",
                "launch_chrome": "python3 scripts/devtools_runtime.py launch-chrome",
                "list_tools": "python3 scripts/devtools_runtime.py mcporter list --schema",
                "sample_call": "python3 scripts/devtools_runtime.py mcporter call chrome-devtools.list_pages",
            },
            "runtime": runtime,
            "server_command": server_command,
        }
    )
    return 0 if mcporter_prefetch["success"] and chrome_prefetch["success"] and daemon_status["success"] else 1


def cmd_launch_chrome(args: argparse.Namespace) -> int:
    port = args.port
    url = args.url or DEFAULT_RAGHOUSE_URL
    try:
        result = launch_chrome(port=port, url=url)
    except RuntimeError as exc:
        return fail(str(exc))

    print_json(result)
    return 0


def cmd_mcporter(args: argparse.Namespace) -> int:
    if not args.mcporter_args:
        return fail("Provide a mcporter subcommand such as `list`, `call`, or `auth`.")

    try:
        ensure_node_runtime()
    except RuntimeError as exc:
        return fail(str(exc))

    subcommand = args.mcporter_args[0]
    passthrough = args.mcporter_args[1:]
    if subcommand not in {"list", "call", "auth"}:
        return fail("This wrapper currently supports only `list`, `call`, and `auth`.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    server_command, _ = chrome_devtools_server_command()
    config_path, _ = write_mcporter_config(server_command)
    daemon_status = ensure_mcporter_daemon(config_path)
    if not daemon_status["success"]:
        return fail(
            "Could not start mcporter daemon. "
            + clean_text(str(daemon_status["stderr"]) or str(daemon_status["stdout"]))
        )

    if subcommand in {"list", "auth"}:
        if not passthrough or passthrough[0].startswith("--"):
            passthrough = [SERVER_NAME, *passthrough]
    elif subcommand == "call":
        if not passthrough:
            return fail("Provide a tool name to call, e.g. `mcporter call chrome-devtools.list_pages`.")
        selector = passthrough[0]
        if "." not in selector and not selector.startswith(("http://", "https://")):
            passthrough = [f"{SERVER_NAME}.{selector}", *passthrough[1:]]

    mcporter_command = [*mcporter_base_command(config_path), subcommand, *passthrough]
    completed = subprocess.run(mcporter_command)
    return completed.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Portable Chrome DevTools MCP helper for raghouse-box-sourcing")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser(
        "bootstrap",
        help="Verify prerequisites and prefetch mcporter + chrome-devtools-mcp via npx",
    )
    bootstrap.set_defaults(func=cmd_bootstrap)

    launch = subparsers.add_parser(
        "launch-chrome",
        help="Launch a dedicated Chrome remote-debugging session with a repo-local profile",
    )
    launch.add_argument("--port", type=int, default=DEFAULT_REMOTE_DEBUGGING_PORT)
    launch.add_argument("--url", default=DEFAULT_RAGHOUSE_URL)
    launch.set_defaults(func=cmd_launch_chrome)

    mcporter = subparsers.add_parser(
        "mcporter",
        help="Proxy `mcporter list|call|auth` against a portable Chrome DevTools MCP runtime",
    )
    mcporter.add_argument("mcporter_args", nargs=argparse.REMAINDER)
    mcporter.set_defaults(func=cmd_mcporter)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
