from __future__ import annotations

from fastapi import APIRouter, HTTPException

from vendoo_studio.services.chrome_bridge import ChromeBridgeError, chrome_executable, relaunch_studio_chrome

router = APIRouter(prefix="/api/desktop", tags=["desktop"])


@router.get("/chrome")
def chrome_status():
    from vendoo_studio.services.chrome_bridge import chrome_profile_dir, installed_extension_dir

    executable = chrome_executable()
    return {
        "available": executable is not None,
        "browser": executable.parent.parent.parent.stem if executable else None,
        "extension_dir": str(installed_extension_dir()),
        "profile_dir": str(chrome_profile_dir()),
    }


@router.post("/chrome/connect")
async def connect_chrome():
    from vendoo_studio.routes.extension import dispatch_show_vendoo, extension_manager
    from vendoo_studio.services.chrome_bridge import extension_build_status

    status = extension_build_status(
        extension_manager.version,
        extension_manager.reload_generation,
    )
    if extension_manager.connected and status.get("up_to_date"):
        sent = await dispatch_show_vendoo()
        if sent:
            return {"ok": True, "via": "extension", "visible": True}
    await extension_manager.disconnect()
    extension_manager.version = None
    extension_manager.reload_generation = None
    try:
        result = relaunch_studio_chrome(visible=True)
        result.setdefault("via", "chrome")
        result["relaunched"] = True
        return result
    except ChromeBridgeError as exc:
        raise HTTPException(400, str(exc)) from exc
