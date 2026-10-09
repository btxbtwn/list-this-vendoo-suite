"""Sign in with a Claude account through the Claude Code CLI.

Studio does not hold Claude credentials. It drives the seller's own Claude
Code install: Settings runs `claude auth login` in a small terminal, the login
lands in Claude Code's keychain entry, `claude auth status` reports it, and the
Agent SDK runs listings on that login. There is no sign-out here: `claude auth
logout` would also sign the seller out of Claude Code itself.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import pty
import shutil
import struct
import subprocess
import termios
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("vendoo_studio.claude_auth")

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


_status: _Status | None = None
_status_guard = threading.Lock()


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
        "install_command": INSTALL_COMMAND,
    }


class LoginTerminal:
    """`claude auth login` on a pseudo-terminal, for the sign-in terminal in Settings.

    It runs that one command, not a shell, and ends when the command does.
    """

    def __init__(self, cols: int = 80, rows: int = 24):
        cli = claude_cli_path()
        if not cli:
            raise RuntimeError(f"Claude Code is not installed. Install it with: {INSTALL_COMMAND}")
        forget_status()
        self._fd, child = pty.openpty()
        self.resize(cols, rows)
        try:
            self.process = subprocess.Popen(
                [cli, "auth", "login", "--claudeai"],
                stdin=child,
                stdout=child,
                stderr=child,
                start_new_session=True,
                env={**os.environ, "TERM": "xterm-256color"},
            )
        finally:
            os.close(child)
        self._output: asyncio.Queue[bytes | None] = asyncio.Queue()
        asyncio.get_running_loop().add_reader(self._fd, self._on_readable)

    def _on_readable(self) -> None:
        try:
            data = os.read(self._fd, 65536)
        except OSError:
            data = b""
        if not data:
            # The command exited and closed its end of the terminal.
            asyncio.get_running_loop().remove_reader(self._fd)
            self._output.put_nowait(None)
            return
        self._output.put_nowait(data)

    async def read(self) -> bytes | None:
        """The next output, or None once the command has exited."""
        return await self._output.get()

    def write(self, data: bytes) -> None:
        os.write(self._fd, data)

    def resize(self, cols: int, rows: int) -> None:
        size = struct.pack("HHHH", max(rows, 1), max(cols, 1), 0, 0)
        fcntl.ioctl(self._fd, termios.TIOCSWINSZ, size)

    async def close(self) -> int | None:
        """Stop the command if it is still running, and return its exit code."""
        if self.process.poll() is None:
            self.process.terminate()
            try:
                await asyncio.to_thread(self.process.wait, 5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                await asyncio.to_thread(self.process.wait)
        if self._fd >= 0:
            asyncio.get_running_loop().remove_reader(self._fd)
            os.close(self._fd)
            self._fd = -1
        forget_status()
        return self.process.returncode
