from __future__ import annotations

from fastapi import APIRouter, HTTPException

from vendoo_studio.services.chrome_bridge import ChromeBridgeError, chrome_executable, relaunch_studio_chrome

router = APIRouter(prefix="/api/desktop", tags=["desktop"])

# Everyday Chrome + MV3 worker wake/reload usually finishes well under this.
CONNECT_WAIT_SEC = 20.0


@router.get("/chrome")
def chrome_status():
    from vendoo_studio.services.chrome_bridge import installed_extension_dir, sync_bundled_extension

    try:
        extension_dir = sync_bundled_extension()
    except ChromeBridgeError:
        extension_dir = installed_extension_dir()
    executable = chrome_executable()
    return {
        "available": executable is not None,
        "browser": executable.parent.parent.parent.stem if executable else None,
        "extension_dir": str(extension_dir),
        "profile": "default",
    }


@router.post("/chrome/connect")
async def connect_chrome():
    try:
        result = relaunch_studio_chrome(visible=True)
        result.setdefault("via", "chrome")
        from vendoo_studio.routes.extension import (
            extension_manager,
            request_extension_reload,
            wait_for_extension_connection,
        )
        from vendoo_studio.services.chrome_bridge import extension_reload_token_if_needed

        token = extension_reload_token_if_needed(
            extension_manager.version,
            extension_manager.reload_generation,
            extension_manager.build,
        )
        if token:
            await request_extension_reload(token)
            result["extension_reload"] = True
        connected = await wait_for_extension_connection(CONNECT_WAIT_SEC)
        result["connected"] = connected
        return result
    except ChromeBridgeError as exc:
        raise HTTPException(400, str(exc)) from exc
