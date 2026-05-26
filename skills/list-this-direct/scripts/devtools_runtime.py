#!/usr/bin/env python3
"""
Portable Chrome DevTools MCP bootstrap/runtime helper for list-this-direct.

This wrapper avoids checkout-specific config paths by:
- verifying local prerequisites
- prefetching `chrome-devtools-mcp` with `npx`
- surfacing a direct MCP server command/config for clients such as Copilot CLI that already support native MCP
- writing a repo-local `mcporter` config only for compatibility-fallback clients that still need it
- keeping the `mcporter` daemon in sync with that fallback runtime definition when used
- optionally launching a dedicated Chrome remote-debugging session with a
  repo-local profile
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from urllib import error, request


SCRIPT_PATH = Path(__file__).resolve()
SKILL_DIR = SCRIPT_PATH.parent.parent
DATA_DIR = SKILL_DIR / "data"
RUNTIME_DIR = DATA_DIR / "runtime"
DEFAULT_REMOTE_DEBUGGING_PORT = 9222
DEFAULT_VENDOO_URL = "https://web.vendoo.co/app/inventory/items"
SERVER_NAME = "chrome-devtools"
MIN_NODE_VERSION = (20, 19, 0)
MCPORTER_CONFIG_PATH = RUNTIME_DIR / "mcporter.json"
BROWSER_STATE_PATH = RUNTIME_DIR / "browser_state.json"
MCPORTER_SERVER_DESCRIPTION = "Repo-local chrome devtools runtime"


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


def join_command(command: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    return shlex.quote(command[0]) + (
        (" " + " ".join(shlex.quote(part) for part in command[1:])) if len(command) > 1 else ""
    )


def env_or_default(name: str, default: str) -> str:
    value = clean_text(os.environ.get(name))
    return value or default


def config_browser_url_candidates() -> list[str]:
    if not MCPORTER_CONFIG_PATH.exists():
        return []
    try:
        payload = json.loads(MCPORTER_CONFIG_PATH.read_text())
        args = payload.get("mcpServers", {}).get(SERVER_NAME, {}).get("args", [])
    except (OSError, json.JSONDecodeError, AttributeError):
        return []
    if not isinstance(args, list):
        return []

    candidates: list[str] = []
    for index, raw_arg in enumerate(args):
        argument = clean_text(raw_arg if isinstance(raw_arg, str) else str(raw_arg))
        if not argument:
            continue
        if argument.startswith("--browser-url="):
            candidates.append(clean_text(argument.split("=", 1)[1]))
            continue
        if argument in {"--browser-url", "--browserUrl", "-u"} and index + 1 < len(args):
            next_arg = args[index + 1]
            candidates.append(clean_text(next_arg if isinstance(next_arg, str) else str(next_arg)))
    return candidates


def nearby_browser_url_candidates(port: int) -> list[str]:
    candidates: list[str] = []
    for candidate_port in range(port, port + 8):
        candidates.append(f"http://127.0.0.1:{candidate_port}")
        candidates.append(f"http://localhost:{candidate_port}")
    return candidates


def browser_url_candidates() -> list[str]:
    remembered = ""
    if BROWSER_STATE_PATH.exists():
        try:
            remembered = clean_text(json.loads(BROWSER_STATE_PATH.read_text()).get("browser_url"))
        except (OSError, json.JSONDecodeError, AttributeError):
            remembered = ""

    explicit = clean_text(
        os.environ.get("LIST_THIS_DIRECT_BROWSER_URL") or os.environ.get("CHROME_DEVTOOLS_BROWSER_URL")
    )
    port_text = env_or_default("LIST_THIS_DIRECT_CHROME_DEBUG_PORT", str(DEFAULT_REMOTE_DEBUGGING_PORT))
    try:
        base_port = int(port_text)
    except ValueError:
        base_port = DEFAULT_REMOTE_DEBUGGING_PORT
    candidates = [
        explicit,
        remembered,
        *config_browser_url_candidates(),
        *nearby_browser_url_candidates(base_port),
    ]
    deduped: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


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

    if env_or_default("LIST_THIS_DIRECT_HEADLESS", "0") in {"1", "true", "yes"}:
        command.append("--headless")

    return command, connection_mode


def write_mcporter_config(server_command: list[str]) -> bool:
    if not server_command:
        raise RuntimeError("Cannot create mcporter config without a Chrome DevTools server command.")

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "mcpServers": {
            SERVER_NAME: {
                "command": server_command[0],
                "args": server_command[1:],
                "description": MCPORTER_SERVER_DESCRIPTION,
            }
        },
        "imports": [],
    }
    config_text = json.dumps(payload, indent=2) + "\n"
    existing_text = None
    if MCPORTER_CONFIG_PATH.exists():
        existing_text = MCPORTER_CONFIG_PATH.read_text()
    if existing_text == config_text:
        return False
    MCPORTER_CONFIG_PATH.write_text(config_text)
    return True


def mcporter_base_command() -> list[str]:
    return ["npx", "-y", "mcporter@latest", "--config", str(MCPORTER_CONFIG_PATH)]


def ensure_mcporter_daemon(config_changed: bool) -> None:
    daemon_subcommand = "restart" if config_changed else "start"
    result = run_command([*mcporter_base_command(), "daemon", daemon_subcommand])
    if result.returncode == 0:
        return
    message = clean_text(result.stderr or result.stdout)
    raise RuntimeError(message or f"`mcporter daemon {daemon_subcommand}` failed.")


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
        os.environ.get("LIST_THIS_DIRECT_CHROME_PATH")
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
            "Could not find a Chrome binary automatically. Set LIST_THIS_DIRECT_CHROME_PATH or CHROME_PATH first."
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
    browser_url = f"http://127.0.0.1:{port}"
    BROWSER_STATE_PATH.write_text(
        json.dumps({"browser_url": browser_url, "pid": process.pid}, indent=2) + "\n"
    )
    return {
        "pid": process.pid,
        "chrome_path": str(chrome_binary),
        "browser_url": browser_url,
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

    print_json(
        {
            "chrome_binary": str(chrome_binary) if chrome_binary else None,
            "copilot_mcp_server": {
                "name": SERVER_NAME,
                "type": "stdio",
                "command": "python3",
                "args": [str(SCRIPT_PATH), "chrome-devtools-server"],
                "env": {},
                "tools": ["*"],
            },
            "connection_mode": connection_mode,
            "detected_browser_url": browser_url,
            "downloads": {
                "chrome_devtools_mcp": chrome_prefetch,
                "mcporter": mcporter_prefetch,
            },
            "next_steps": {
                "bootstrap": "python3 scripts/devtools_runtime.py bootstrap",
                "copilot_native_mcp": "If the current client already supports MCP directly, register the copilot_mcp_server entry instead of routing through mcporter.",
                "launch_chrome": "python3 scripts/devtools_runtime.py launch-chrome",
                "list_tools": "python3 scripts/devtools_runtime.py mcporter list",
                "sample_call": "python3 scripts/devtools_runtime.py mcporter call list_pages",
            },
            "mcporter_config": portable_path(MCPORTER_CONFIG_PATH),
            "runtime": runtime,
            "server_command": server_command,
        }
    )
    return 0 if mcporter_prefetch["success"] and chrome_prefetch["success"] else 1


def cmd_launch_chrome(args: argparse.Namespace) -> int:
    port = args.port
    url = args.url or DEFAULT_VENDOO_URL
    try:
        result = launch_chrome(port=port, url=url)
    except RuntimeError as exc:
        return fail(str(exc))

    print_json(result)
    return 0


def cmd_chrome_devtools_server(_: argparse.Namespace) -> int:
    try:
        ensure_node_runtime()
        server_command, _ = chrome_devtools_server_command()
    except RuntimeError as exc:
        return fail(str(exc))

    os.execvp(server_command[0], server_command)
    return 1


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

    server_command, _ = chrome_devtools_server_command()
    try:
        config_changed = write_mcporter_config(server_command)
        ensure_mcporter_daemon(config_changed)
    except (OSError, RuntimeError) as exc:
        return fail(str(exc))

    if subcommand in {"list", "auth"}:
        if not passthrough or passthrough[0].startswith("-"):
            passthrough = [SERVER_NAME, *passthrough]
    elif subcommand == "call":
        if not passthrough:
            return fail("Provide a tool selector such as `list_pages` or `chrome-devtools.list_pages`.")
        selector = passthrough[0]
        if "://" not in selector and "." not in selector:
            selector = f"{SERVER_NAME}.{selector}"
        passthrough = [selector, *passthrough[1:]]

    mcporter_command = [*mcporter_base_command(), subcommand, *passthrough]
    completed = subprocess.run(mcporter_command)
    return completed.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Portable Chrome DevTools MCP helper for list-this-direct")
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
    launch.add_argument("--url", default=DEFAULT_VENDOO_URL)
    launch.set_defaults(func=cmd_launch_chrome)

    direct_server = subparsers.add_parser(
        "chrome-devtools-server",
        help="Launch chrome-devtools-mcp directly with the best detected browser-url for native MCP clients",
    )
    direct_server.set_defaults(func=cmd_chrome_devtools_server)

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
