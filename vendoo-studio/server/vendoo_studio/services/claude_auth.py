"""Sign in with a Claude account through the Claude Code CLI.

Studio does not hold Claude credentials. Like T3 Code, it drives the seller's
own Claude Code install: `claude auth login` stores the subscription login in
Claude Code's keychain entry, `claude auth status` reports it, and the Agent
SDK runs listings on that login. There is no sign-out here: `claude auth logout`
would also sign the seller out of Claude Code itself.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("vendoo_studio.claude_auth")

LOGIN_TIMEOUT_S = 15 * 60
STATUS_TTL_S = 60
STATUS_TIMEOUT_S = 15
INSTALL_COMMAND = "curl -fsSL https://claude.ai/install.sh | bash"
# A Finder-launched app gets a bare PATH, so look where the installers put it.
CLI_LOCATIONS = (
    "~/.local/bin/claude",
    "~/.claude/local/claude",
    "/opt/homebrew/bin/claude",
    "/usr/local/bin/claude",
)
_URL_RE = re.compile(r"https://\S+")


def claude_cli_path() -> str | None:
    """The seller's Claude Code CLI, else the copy the Agent SDK ships in dev installs."""
    found = shutil.which("claude")
    if found:
        return found
    for location in CLI_LOCATIONS:
        path = Path(location).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    try:
        import claude_agent_sdk
    except ImportError:
        return None
    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
    return str(bundled) if bundled.is_file() else None


@dataclass
class _Status:
    installed: bool
    signed_in: bool
    email: str | None = None
    plan: str | None = None
    checked_at: float = field(default_factory=time.monotonic)


@dataclass
class PendingLogin:
    process: asyncio.subprocess.Process
    url: str | None = None
    task: asyncio.Task | None = None
    error: str | None = None
    done: bool = False


_status: _Status | None = None
_status_guard = threading.Lock()
_pending: PendingLogin | None = None


def _read_status() -> _Status:
    cli = claude_cli_path()
    if not cli:
        return _Status(installed=False, signed_in=False)
    try:
        result = subprocess.run(
            [cli, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=STATUS_TIMEOUT_S,
            check=False,
        )
        data = json.loads(result.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        log.warning("claude auth status failed", exc_info=True)
        return _Status(installed=True, signed_in=False)
    if not isinstance(data, dict):
        return _Status(installed=True, signed_in=False)
    email = data.get("email")
    plan = data.get("subscriptionType")
    return _Status(
        installed=True,
        signed_in=bool(data.get("loggedIn")),
        email=email if isinstance(email, str) and email else None,
        plan=plan if isinstance(plan, str) and plan else None,
    )


def _current_status() -> _Status:
    """`claude auth status` takes a few hundred ms, so health polls read a cached answer."""
    global _status
    with _status_guard:
        if _status is None or time.monotonic() - _status.checked_at > STATUS_TTL_S:
            _status = _read_status()
        return _status


def forget_status() -> None:
    global _status
    with _status_guard:
        _status = None


def claude_signed_in() -> bool:
    return _current_status().signed_in


def status() -> dict:
    current = _current_status()
    return {
        "installed": current.installed,
        "signed_in": current.signed_in,
        "email": current.email,
        "plan": current.plan,
        "pending": pending_login(),
        "error": None if current.signed_in else login_error(),
        "install_command": INSTALL_COMMAND,
    }


async def start_login() -> dict:
    global _pending
    await cancel_login()
    forget_status()
    cli = claude_cli_path()
    if not cli:
        raise RuntimeError(f"Claude Code is not installed. Install it with: {INSTALL_COMMAND}")
    # The CLI opens the browser itself and finishes on its local callback;
    # the code prompt on stdin is the fallback when that callback can't land.
    process = await asyncio.create_subprocess_exec(
        cli,
        "auth",
        "login",
        "--claudeai",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    pending = PendingLogin(process=process)
    pending.task = asyncio.create_task(_complete_login(pending))
    _pending = pending
    # Show the sign-in link as soon as the CLI prints it.
    for _ in range(50):
        if pending.url or pending.done:
            break
        await asyncio.sleep(0.1)
    if pending.done and pending.error:
        raise RuntimeError(pending.error)
    return {"url": pending.url}


async def _complete_login(pending: PendingLogin) -> None:
    process = pending.process
    output: list[str] = []

    async def read_output() -> None:
        assert process.stdout is not None
        async for raw in process.stdout:
            line = raw.decode("utf-8", "replace").replace("Paste code here if prompted >", "").strip()
            output.append(line)
            match = _URL_RE.search(line)
            if match and pending.url is None:
                pending.url = match.group()

    try:
        await asyncio.wait_for(read_output(), timeout=LOGIN_TIMEOUT_S)
        code = await process.wait()
        if code != 0:
            detail = next((line for line in reversed(output) if line), "")
            if "status code 400" in detail:
                detail = "Claude did not accept that code. Sign in again and paste the newest code."
            pending.error = detail or f"Claude sign-in failed (exit {code})"
    except TimeoutError:
        pending.error = "Claude sign-in timed out after 15 minutes"
    except asyncio.CancelledError:
        pending.error = "Login cancelled"
        raise
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        pending.done = True
        forget_status()


async def submit_code(code: str) -> None:
    """Finish a login whose browser could not reach the CLI by pasting the code it showed."""
    pending = _pending
    if pending is None or pending.done or pending.process.stdin is None:
        raise RuntimeError("No Claude sign-in is waiting for a code.")
    pending.process.stdin.write(code.strip().encode() + b"\n")
    await pending.process.stdin.drain()
    if pending.task is not None:
        try:
            await asyncio.wait_for(asyncio.shield(pending.task), timeout=30)
        except TimeoutError:
            pass
    if pending.error:
        raise RuntimeError(pending.error)


async def cancel_login() -> None:
    global _pending
    previous, _pending = _pending, None
    if previous and previous.task and not previous.task.done():
        previous.task.cancel()
        try:
            await previous.task
        except asyncio.CancelledError:
            pass


def pending_login() -> dict | None:
    if not _pending or _pending.done:
        return None
    return {"url": _pending.url}


def login_error() -> str | None:
    if _pending and _pending.done:
        return _pending.error
    return None

