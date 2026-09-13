from __future__ import annotations

from fastapi import APIRouter, HTTPException

from vendoo_studio.services.chrome_bridge import ChromeBridgeError, chrome_executable, launch_studio_chrome

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

    if extension_manager.connected:
        sent = await dispatch_show_vendoo()
        if sent:
            return {"ok": True, "via": "extension", "visible": True}
    try:
        result = launch_studio_chrome(visible=True)
        result.setdefault("via", "chrome")
        return result
    except ChromeBridgeError as exc:
        raise HTTPException(400, str(exc)) from exc
