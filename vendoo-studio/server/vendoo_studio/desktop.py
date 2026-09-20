from __future__ import annotations

import html
import json
import multiprocessing
import os
import plistlib
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from vendoo_studio.config import BASE_DIR, HOST, PORT, extension_source_dir, frontend_dist_dir, is_frozen
from vendoo_studio.version import app_version

CHANNELS = {
    "production": {
        "app_name": "List This Studio",
        "bundle_id": "local.listthis.studio",
        "executable": "ListThisStudio",
        "port": "4318",
        "ref": "main",
        "log": "ListThisStudio.log",
    },
    "staging": {
        "app_name": "List This Studio Staging",
        "bundle_id": "local.listthis.studio.staging",
        "executable": "ListThisStudioStaging",
        "port": "4319",
        "ref": "staging",
        "log": "ListThisStudioStaging.log",
    },
}

CHANNEL_NAME = os.environ.get("VENDOO_STUDIO_CHANNEL", "production")
CHANNEL = CHANNELS.get(CHANNEL_NAME, CHANNELS["production"])
APP_NAME = CHANNEL["app_name"]
BUNDLE_ID = CHANNEL["bundle_id"]
APP_EXECUTABLE = CHANNEL["executable"]
WINDOW_WIDTH = 1440
WINDOW_HEIGHT = 900
MIN_WINDOW_SIZE = (1024, 700)
WINDOW_BACKGROUND = "#090909"
# T3 Code's macOS chrome: a 52pt topbar with Electron `hiddenInset` traffic
# lights parked at x=16, vertically centred on that band. The buttons keep their
# standard AppKit size — 14pt circles on a 20pt pitch — so ours must too.
TITLEBAR_HEIGHT_PX = 52
TRAFFIC_LIGHT_SIZE_PX = 14.0
TRAFFIC_LIGHT_GAP_PX = 6.0
TRAFFIC_LIGHT_X_PX = 16.0
HEALTH_URL = f"http://{HOST}:{PORT}/api/health"
APP_URL = f"http://{HOST}:{PORT}"
LOG_PATH = Path.home() / "Library" / "Application Support" / CHANNEL["app_name"] / "logs" / CHANNEL["log"]

_server = None
_server_thread: threading.Thread | None = None
_owned_server = False


def augment_path() -> None:
    extras = [
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
        Path.home() / ".local" / "bin",
        Path.home() / ".volta" / "bin",
        Path.home() / ".fnm" / "current" / "bin",
        Path.home() / ".asdf" / "shims",
    ]
    nvm_nodes = Path.home() / ".nvm" / "versions" / "node"
    if nvm_nodes.is_dir():
        extras.extend(sorted((nvm_nodes).glob("*/bin"), reverse=True))
    existing = os.environ.get("PATH", "")
    prefix = os.pathsep.join(str(path) for path in extras if path.exists())
    os.environ["PATH"] = f"{prefix}{os.pathsep}{existing}" if prefix else existing


def venv_python() -> Path:
    return BASE_DIR / ".venv" / "bin" / "python"


def running_in_venv() -> bool:
    return Path(sys.executable).resolve() == venv_python().resolve()


def python_is_supported(executable: str) -> bool:
    probe = subprocess.run(
        [executable, "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"],
        capture_output=True,
    )
    return probe.returncode == 0


def pick_python() -> str:
    candidates = [
        str(venv_python()),
        "/opt/homebrew/bin/python3.13",
        "/opt/homebrew/bin/python3.12",
        "/usr/local/bin/python3.13",
        "/usr/local/bin/python3.12",
    ]
    for name in ("python3.13", "python3.12", "python3"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen or not Path(candidate).exists():
            continue
        seen.add(candidate)
        if python_is_supported(candidate):
            return candidate
    raise RuntimeError(
        "Python 3.12 or newer is required. Install it with Homebrew (`brew install python@3.12`) and reopen List This Studio."
    )


def require_command(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(
            f"{name} is not installed. Install Node.js from https://nodejs.org then reopen List This Studio."
            if name == "npm"
            else f"{name} was not found on PATH."
        )
    return path


def setup_logging() -> None:
    if sys.stderr.isatty():
        return
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = open(LOG_PATH, "a", encoding="utf-8")
    sys.stdout = handle
    sys.stderr = handle


def splash_html(message: str = "Starting List This Studio…") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{APP_NAME}</title>
  <style>
    :root {{ color-scheme: dark; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: {WINDOW_BACKGROUND};
      color: #E2E3E5;
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .pywebview-drag-region {{
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      height: {TITLEBAR_HEIGHT_PX}px;
    }}
    main {{ text-align: center; max-width: 28rem; padding: 2rem; }}
    h1 {{ font-size: 1.15rem; font-weight: 600; color: #fff; margin: 0 0 .75rem; }}
    p {{ margin: 0; color: #97979A; line-height: 1.5; }}
  </style>
</head>
<body>
  <div class="pywebview-drag-region" aria-hidden="true"></div>
  <main>
    <h1>{html.escape(APP_NAME)}</h1>
    <p>{html.escape(message)}</p>
  </main>
</body>
</html>
"""


def error_html(message: str) -> str:
    return splash_html(message)


def studio_is_up() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=0.6) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload.get("service") == "vendoo-studio"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False


def port_is_open() -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(0.3)
        return sock.connect_ex((HOST, PORT)) == 0
    finally:
        sock.close()


def wait_for_studio(timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if studio_is_up():
            return
        time.sleep(0.15)
    raise RuntimeError(f"{APP_NAME} did not start at {APP_URL}.")


def notify(message: str) -> None:
    print(message, flush=True)
    if not shutil.which("osascript"):
        return
    subprocess.run(
        [
            "osascript",
            "-e",
            f"display notification {shlex_quote(message)} with title {shlex_quote(APP_NAME)}",
        ],
        check=False,
    )


def confirm_update_dialog(message: str, *, confirm_label: str = "Update") -> bool:
    """Native confirm for menu-bar updates when the web UI may be unusable."""
    if not shutil.which("osascript"):
        return True
    script = (
        f'display dialog {shlex_quote(message)} with title {shlex_quote(APP_NAME)} '
        f'buttons {{"Cancel", {shlex_quote(confirm_label)}}} default button {shlex_quote(confirm_label)} '
        f'cancel button "Cancel"'
    )
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return result.returncode == 0 and confirm_label in (result.stdout or "")


def _update_status_message(status: dict) -> str:
    if status.get("error"):
        return str(status["error"])
    if not status.get("available"):
        return f"{APP_NAME} is up to date."
    version = status.get("short_sha") or (
        (status.get("remote_sha") or "")[:7] if status.get("remote_sha") else ""
    )
    summary = status.get("summary") or "An update is available."
    if version:
        return f"Update {version} available. {summary}"
    return str(summary)


def _http_apply_update() -> dict:
    request = urllib.request.Request(
        f"{APP_URL}/api/updates/apply",
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_reinstall_app() -> dict:
    request = urllib.request.Request(
        f"{APP_URL}/api/updates/reinstall",
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_check_updates() -> dict:
    with urllib.request.urlopen(f"{APP_URL}/api/updates", timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def menu_check_for_updates() -> None:
    def work() -> None:
        try:
            notify("Checking for updates…")
            if studio_is_up():
                status = _http_check_updates()
            else:
                from vendoo_studio.services.updates import check_for_updates

                status = check_for_updates()
            notify(_update_status_message(status))
        except Exception as exc:
            notify(f"Could not check for updates: {exc}")

    threading.Thread(target=work, daemon=True, name="studio-menu-check-updates").start()


def menu_update_and_restart() -> None:
    def work() -> None:
        try:
            notify("Checking for updates…")
            if studio_is_up():
                status = _http_check_updates()
            else:
                from vendoo_studio.services.updates import check_for_updates

                status = check_for_updates()
            if status.get("error") and not status.get("available"):
                notify(str(status["error"]))
                return
            if not status.get("available"):
                notify(f"{APP_NAME} is up to date.")
                return
            message = (
                f"{_update_status_message(status)}\n\n"
                "Install this update and restart? Running tasks will be interrupted."
            )
            if not confirm_update_dialog(message):
                notify("Update cancelled.")
                return
            notify("Installing update…")
            if studio_is_up():
                result = _http_apply_update()
            else:
                from vendoo_studio.services.updates import apply_update, schedule_restart

                result = apply_update()
                if result.get("updated"):
                    schedule_restart()
            if result.get("updated"):
                notify("Update installed. Restarting…")
            else:
                notify(f"{APP_NAME} is up to date.")
        except Exception as exc:
            notify(f"Update failed: {exc}")

    threading.Thread(target=work, daemon=True, name="studio-menu-apply-update").start()


def menu_reinstall_app() -> None:
    def work() -> None:
        try:
            message = (
                "Download a fresh Mac build from GitHub and replace this app?\n\n"
                "Listing data and settings stay on this Mac. The app will quit and reopen."
            )
            if not confirm_update_dialog(message, confirm_label="Reinstall"):
                notify("Reinstall cancelled.")
                return
            notify("Reinstalling from GitHub…")
            if studio_is_up():
                result = _http_reinstall_app()
            else:
                from vendoo_studio.services.updates import reinstall_app, schedule_restart

                result = reinstall_app()
                if result.get("updated"):
                    schedule_restart()
            if result.get("updated"):
                notify("Reinstall complete. Restarting…")
            else:
                notify(f"{APP_NAME} could not be reinstalled.")
        except Exception as exc:
            notify(f"Reinstall failed: {exc}")

    threading.Thread(target=work, daemon=True, name="studio-menu-reinstall").start()


def studio_app_menu():
    """Native macOS menu bar items that work even when the web UI is blank."""
    try:
        from webview.menu import Menu, MenuAction, MenuSeparator
    except ImportError:
        return []

    app_items = [
        MenuAction("Check for Updates…", menu_check_for_updates),
        MenuAction("Update and Restart…", menu_update_and_restart),
        MenuAction("Reinstall from GitHub…", menu_reinstall_app),
        MenuSeparator(),
    ]
    return [
        # macOS only: items under the app name in the system menu bar.
        Menu("__app__", app_items),
        Menu(
            "Studio",
            [
                MenuAction("Check for Updates…", menu_check_for_updates),
                MenuAction("Update and Restart…", menu_update_and_restart),
                MenuAction("Reinstall from GitHub…", menu_reinstall_app),
            ],
        ),
    ]



def ensure_venv() -> Path:
    python = venv_python()
    if not python.exists():
        notify("Installing List This Studio. This can take a minute on first launch.")
        creator = pick_python()
        subprocess.run([creator, "-m", "venv", str(BASE_DIR / ".venv")], check=True)
        subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"], check=True)
        subprocess.run([str(python), "-m", "pip", "install", "-e", ".[desktop]"], cwd=str(BASE_DIR), check=True)
        return python
    probe = subprocess.run(
        [str(python), "-c", "import fastapi, uvicorn, webview"],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        notify("Updating List This Studio Python packages…")
        subprocess.run([str(python), "-m", "pip", "install", "-e", ".[desktop]"], cwd=str(BASE_DIR), check=True)
    return python


def reexec_in_venv_if_needed() -> None:
    python = ensure_venv()
    if running_in_venv():
        return
    os.execv(str(python), [str(python), "-m", "vendoo_studio.desktop", *sys.argv[1:]])


def ensure_on_channel_ref() -> None:
    from vendoo_studio.services.updates import (
        REF,
        current_branch,
        ensure_standalone_clone,
        pin_to_remote,
        repo_root,
    )

    root = ensure_standalone_clone(repo_root())
    if current_branch(root) == REF:
        return
    pin_to_remote(root, f"origin/{REF}")


def ensure_frontend() -> None:
    index = frontend_dist_dir() / "index.html"
    if index.exists():
        return
    if is_frozen():
        raise RuntimeError("The listing UI is missing from this app. Re-download List This Studio.")
    npm = require_command("npm")
    if not (BASE_DIR / "node_modules").exists():
        subprocess.run([npm, "install"], cwd=BASE_DIR, check=True)
    subprocess.run([npm, "run", "build"], cwd=BASE_DIR, check=True)
    if not index.exists():
        raise RuntimeError("The frontend build finished without creating dist/index.html.")


def start_owned_server() -> None:
    global _server, _server_thread, _owned_server
    if studio_is_up():
        _owned_server = False
        return
    if port_is_open():
        raise RuntimeError(
            f"Port {PORT} is already in use by another app. Quit that process and reopen {APP_NAME}."
        )

    import uvicorn
    from vendoo_studio.main import app

    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="info", access_log=False)
    _server = uvicorn.Server(config)
    _server_thread = threading.Thread(target=_server.run, daemon=True, name="vendoo-studio-uvicorn")
    _server_thread.start()
    _owned_server = True
    wait_for_studio()


def stop_owned_server() -> None:
    global _server, _owned_server
    if not _owned_server or _server is None:
        return
    _server.should_exit = True
    _owned_server = False


def default_app_path(channel_name: str = "production") -> Path:
    applications = Path.home() / "Applications"
    applications.mkdir(parents=True, exist_ok=True)
    return applications / f"{CHANNELS[channel_name]['app_name']}.app"


def channel_source_dir(channel_name: str) -> Path:
    support_name = "ListThisStudio" if channel_name == "production" else "ListThisStudioStaging"
    return Path.home() / "Library" / "Application Support" / support_name / "src"


def ensure_channel_source(channel_name: str) -> Path:
    from vendoo_studio.services.updates import remote_url

    channel = CHANNELS[channel_name]
    source = channel_source_dir(channel_name)
    git_dir = source / ".git"
    if not git_dir.exists() and not git_dir.is_file():
        source.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--branch", channel["ref"], "--single-branch", remote_url(), str(source)],
            check=True,
        )
    return source / "vendoo-studio"


def install_macos_app(destination: Path | None = None, channel_name: str = "production") -> Path:
    channel = CHANNELS[channel_name]
    studio_dir = ensure_channel_source(channel_name)
    app_path = destination or default_app_path(channel_name)
    macos = app_path / "Contents" / "MacOS"
    resources = app_path / "Contents" / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    plist = {
        "CFBundleName": channel["app_name"],
        "CFBundleDisplayName": channel["app_name"],
        "CFBundleIdentifier": channel["bundle_id"],
        "CFBundleVersion": app_version(),
        "CFBundleShortVersionString": app_version(),
        "CFBundleExecutable": channel["executable"],
        "CFBundlePackageType": "APPL",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    }
    icon_name = install_bundle_icon(resources)
    if icon_name:
        plist["CFBundleIconFile"] = icon_name
    with (app_path / "Contents" / "Info.plist").open("wb") as handle:
        plistlib.dump(plist, handle)
    launcher = macos / channel["executable"]
    launcher.write_text(launcher_script(studio_dir, channel_name), encoding="utf-8")
    launcher.chmod(0o755)
    return app_path


def launcher_script(studio_dir: Path, channel_name: str) -> str:
    from vendoo_studio.services.updates import remote_url

    channel = CHANNELS[channel_name]
    return f"""#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin:$PATH"
export VENDOO_STUDIO_CHANNEL={shlex_quote(channel_name)}
export VENDOO_STUDIO_PORT={shlex_quote(channel["port"])}
export VENDOO_STUDIO_UPDATE_REF={shlex_quote(channel["ref"])}
export VENDOO_STUDIO_UPDATE_URL={shlex_quote(remote_url())}
STUDIO_DIR={shlex_quote(str(studio_dir))}
cd "$STUDIO_DIR" || exit 1
export PYTHONPATH="$STUDIO_DIR/server"
LOG="$HOME/Library/Application Support/{channel["app_name"]}/logs/{channel["log"]}"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "$(date) starting {channel["app_name"]}"
pick_python() {{
  local candidate
  for candidate in \\
    "$STUDIO_DIR/.venv/bin/python" \\
    /opt/homebrew/bin/python3.13 \\
    /opt/homebrew/bin/python3.12 \\
    /usr/local/bin/python3.13 \\
    /usr/local/bin/python3.12 \\
    "$(command -v python3.13 || true)" \\
    "$(command -v python3.12 || true)" \\
    "$(command -v python3 || true)"; do
    if [[ -x "$candidate" ]] && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
      printf '%s\\n' "$candidate"
      return 0
    fi
  done
  return 1
}}
PYTHON="$(pick_python)" || {{
  /usr/bin/osascript -e 'display dialog "{channel["app_name"]} needs Python 3.12 or newer. Install it with Homebrew (brew install python@3.12) and try again." buttons {{"OK"}} default button 1 with title "{channel["app_name"]}"'
  exit 1
}}
"$PYTHON" -m vendoo_studio.desktop
"""


def shlex_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def extension_app_icon_path() -> Path | None:
    path = extension_source_dir() / "icons" / "icon128.png"
    return path if path.is_file() else None


def install_bundle_icon(resources: Path) -> str | None:
    source = extension_app_icon_path()
    if source is None:
        return None
    resources.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, resources / "AppIcon.png")
    icns = resources / "AppIcon.icns"
    try:
        from importlib.util import module_from_spec, spec_from_file_location

        make_icon_path = Path(__file__).resolve().parent.parent.parent / "desktop" / "make_icon.py"
        spec = spec_from_file_location("make_icon", make_icon_path)
        if spec is not None and spec.loader is not None:
            module = module_from_spec(spec)
            spec.loader.exec_module(module)
            module.write_icns(icns)
    except Exception:
        pass
    if icns.is_file():
        return "AppIcon"
    return "AppIcon.png"


def studio_window_kwargs() -> dict:
    return {
        "width": WINDOW_WIDTH,
        "height": WINDOW_HEIGHT,
        "min_size": MIN_WINDOW_SIZE,
        "text_select": True,
        "frameless": True,
        "easy_drag": False,
        "shadow": True,
        "background_color": WINDOW_BACKGROUND,
    }


def studio_start_kwargs() -> dict:
    icon = extension_app_icon_path()
    kwargs: dict = {"menu": studio_app_menu()}
    if icon is not None:
        kwargs["icon"] = str(icon)
    return kwargs


def _hex_to_srgb(color: str) -> tuple[float, float, float]:
    value = color.removeprefix("#")
    return (
        int(value[0:2], 16) / 255.0,
        int(value[2:4], 16) / 255.0,
        int(value[4:6], 16) / 255.0,
    )


def traffic_light_rect(index: int, container_height: float) -> tuple[float, float, float, float]:
    """Electron hiddenInset geometry used by T3 Code: 14pt buttons, 6pt gap."""
    size = TRAFFIC_LIGHT_SIZE_PX
    x = TRAFFIC_LIGHT_X_PX + index * (size + TRAFFIC_LIGHT_GAP_PX)
    y = max(0.0, float(container_height) - (TITLEBAR_HEIGHT_PX + size) / 2.0)
    return (x, y, size, size)


def _layout_t3_traffic_lights(native, AppKit) -> None:
    buttons = (
        AppKit.NSWindowCloseButton,
        AppKit.NSWindowMiniaturizeButton,
        AppKit.NSWindowZoomButton,
    )
    container_height = float(TITLEBAR_HEIGHT_PX)
    try:
        close = native.standardWindowButton_(buttons[0])
        if close is not None:
            superview = close.superview()
            if superview is not None:
                container_height = float(superview.frame().size.height)
    except Exception:
        pass

    make_rect = getattr(AppKit, "NSMakeRect", None)
    for index, button in enumerate(buttons):
        try:
            control = native.standardWindowButton_(button)
            if control is None:
                continue
            control.setHidden_(False)
            # No setControlSize_ here: T3 Code leaves the buttons at their
            # regular AppKit size, and the small size shrinks the glyphs.
            control.setEnabled_(True)
            x, y, width, height = traffic_light_rect(index, container_height)
            if make_rect is not None:
                control.setFrame_(make_rect(x, y, width, height))
            else:
                frame = control.frame()
                frame.origin.x = x
                frame.origin.y = y
                frame.size.width = width
                frame.size.height = height
                control.setFrame_(frame)
        except Exception:
            pass


def _enable_window_buttons(native, AppKit) -> None:
    """Close, miniaturize, and zoom only act when the mask carries their bits.

    pywebview's frameless window drops them, which leaves T3 Code's traffic
    lights drawn but dead. Titled + full-size content view keeps the frameless
    look while AppKit wires the buttons back up.
    """
    wanted = 0
    for name, fallback in (
        ("NSWindowStyleMaskTitled", 1 << 0),
        ("NSWindowStyleMaskClosable", 1 << 1),
        ("NSWindowStyleMaskMiniaturizable", 1 << 2),
        ("NSWindowStyleMaskResizable", 1 << 3),
        ("NSWindowStyleMaskFullSizeContentView", 1 << 15),
    ):
        wanted |= _macos_flag(AppKit, name, fallback)
    try:
        current = int(native.styleMask())
    except Exception:
        current = 0
    try:
        native.setStyleMask_(current | wanted)
    except Exception:
        pass


def _macos_flag(AppKit, name: str, fallback: int) -> int:
    return int(getattr(AppKit, name, fallback))


def _is_native_fullscreen(native, AppKit) -> bool:
    try:
        mask = int(native.styleMask())
    except Exception:
        return False
    return bool(mask & _macos_flag(AppKit, "NSFullScreenWindowMask", 1 << 14))


def _disable_native_fullscreen(native, AppKit) -> None:
    """Keep zoom-to-fill, but block Spaces fullscreen. Frameless WKWebView crashes there."""
    none = _macos_flag(AppKit, "NSWindowCollectionBehaviorFullScreenNone", 1 << 9)
    primary = _macos_flag(AppKit, "NSWindowCollectionBehaviorFullScreenPrimary", 1 << 7)
    try:
        current = int(native.collectionBehavior())
    except Exception:
        current = 0
    try:
        native.setCollectionBehavior_((current & ~primary) | none)
    except Exception:
        pass


def apply_unified_macos_chrome(window, *_args, **_kwargs) -> None:
    """Paint the window like T3 Code: no grey title bar, 12pt traffic lights on the UI."""
    if sys.platform != "darwin":
        return
    _set_macos_app_icon()
    native = getattr(window, "native", None)
    if native is None:
        return
    try:
        import AppKit
    except ImportError:
        return

    if _is_native_fullscreen(native, AppKit):
        return

    _disable_native_fullscreen(native, AppKit)
    _enable_window_buttons(native, AppKit)

    title_hidden = getattr(AppKit, "NSWindowTitleHidden", 1)
    try:
        native.setTitlebarAppearsTransparent_(True)
        native.setTitleVisibility_(title_hidden)
        red, green, blue = _hex_to_srgb(WINDOW_BACKGROUND)
        native.setBackgroundColor_(
            AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(red, green, blue, 1.0)
        )
        appearance = AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameDarkAqua)
        native.setAppearance_(appearance)
        content = native.contentView()
        superview = content.superview() if content is not None else None
        subviews = list(superview.subviews()) if superview is not None else []
        if subviews:
            subviews[-1].setBackgroundColor_(AppKit.NSColor.clearColor())
    except Exception:
        pass

    _layout_t3_traffic_lights(native, AppKit)


def create_studio_window(webview_module):
    window = webview_module.create_window(
        APP_NAME,
        html=splash_html(),
        **studio_window_kwargs(),
    )
    window.events.before_show += apply_unified_macos_chrome
    events = window.events
    if hasattr(events, "shown"):
        events.shown += apply_unified_macos_chrome
    if hasattr(events, "restored"):
        events.restored += apply_unified_macos_chrome
    return window


def _set_macos_app_name() -> None:
    try:
        from Foundation import NSBundle
    except ImportError:
        return
    bundle = NSBundle.mainBundle()
    info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
    if info is None:
        return
    info["CFBundleName"] = APP_NAME
    info["CFBundleDisplayName"] = APP_NAME


def _set_macos_app_icon() -> None:
    icon = extension_app_icon_path()
    if icon is None:
        return
    try:
        from AppKit import NSApplication, NSImage
    except Exception:
        return
    image = NSImage.alloc().initWithContentsOfFile_(str(icon))
    if image is None:
        return
    NSApplication.sharedApplication().setApplicationIconImage_(image)


def _boot_window(window) -> None:
    try:
        window.load_html(splash_html("Preparing the listing workspace…"))
        if not is_frozen():
            ensure_on_channel_ref()
        ensure_frontend()
        # Unlock Keychain on the UI thread before generate can block on it.
        # Click Always Allow if macOS asks — otherwise remote generate hangs.
        window.load_html(splash_html("Unlocking Keychain secrets…"))
        try:
            from vendoo_studio.services.keychain import warm_keychain
            warm_keychain()
        except Exception:
            pass
        window.load_html(splash_html("Starting the local studio server…"))
        start_owned_server()
        window.load_url(APP_URL)
    except Exception as exc:
        window.load_html(error_html(str(exc)))


def enable_editable_context_menus() -> None:
    """Keep Cut/Copy/Paste in WKWebView right-click menus.

    pywebview clears every context-menu item unless debug is on, which makes
    Paste unavailable in the chat composer and other text fields.
    """
    try:
        from Foundation import NSStringFromSelector
        from webview.platforms.cocoa import BrowserView
    except Exception:
        return

    allowed_actions = {
        "cut:",
        "copy:",
        "paste:",
        "pasteAndMatchStyle:",
        "selectAll:",
        "delete:",
    }
    allowed_titles = {
        "cut",
        "copy",
        "paste",
        "paste and match style",
        "select all",
        "delete",
    }

    def will_open_menu(self, menu, event):  # noqa: ANN001
        try:
            items = list(menu.itemArray() or [])
        except Exception:
            try:
                menu.removeAllItems()
            except Exception:
                pass
            return
        keep = []
        for item in items:
            try:
                action = item.action()
                title = str(item.title() or "").strip().casefold()
            except Exception:
                continue
            action_name = ""
            if action is not None:
                try:
                    action_name = str(NSStringFromSelector(action) or "")
                except Exception:
                    action_name = str(action)
            if action_name in allowed_actions or title in allowed_titles:
                keep.append(item)
        try:
            menu.removeAllItems()
            for item in keep:
                menu.addItem_(item)
        except Exception:
            pass

    try:
        BrowserView.WebKitHost.willOpenMenu_withEvent_ = will_open_menu
    except Exception:
        pass


def run_window() -> None:
    _set_macos_app_name()
    _set_macos_app_icon()
    import webview

    enable_editable_context_menus()
    window = create_studio_window(webview)
    webview.start(lambda: _boot_window(window), **studio_start_kwargs())
    stop_owned_server()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if is_frozen():
        os.environ.setdefault("VENDOO_STUDIO_PACKAGED", "1")
        setup_logging()
        print(f"starting {APP_NAME}", flush=True)
        run_window()
        return 0
    augment_path()
    if "--install-staging" in args:
        path = install_macos_app(channel_name="staging")
        print(f"Installed {path}")
        print("Open it from Spotlight or Applications: List This Studio Staging")
        return 0
    if "--install" in args:
        path = install_macos_app(channel_name="production")
        print(f"Installed {path}")
        print("Open it from Spotlight or Applications: List This Studio")
        return 0
    setup_logging()
    reexec_in_venv_if_needed()
    run_window()
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
