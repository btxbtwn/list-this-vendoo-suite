"""Current built UI with absent dependencies in a disposable data directory.

Credential reads return absent; credential writes and external-action routes are
blocked by the harness. This is an isolated UI fault fixture, not real sign-out.
"""
from contextlib import ExitStack
import os
import tempfile
from unittest.mock import patch

with tempfile.TemporaryDirectory(prefix="vendoo-isolated-ui-") as tmp, ExitStack() as stack:
    os.environ["VENDOO_STUDIO_DATA_DIR"]=tmp
    for name in ["get_api_key","get_brave_api_key","get_chatgpt_tokens"]:
        stack.enter_context(patch("vendoo_studio.services.keychain."+name,return_value=None))
    stack.enter_context(patch("vendoo_studio.services.keychain.get_chatgpt_models",return_value={}))
    stack.enter_context(patch("vendoo_studio.services.chrome_bridge.chrome_executable",return_value=None))
    stack.enter_context(patch("vendoo_studio.services.chrome_bridge.install_bundled_extension",return_value=None))
    from fastapi.responses import JSONResponse
    from vendoo_studio.main import app
    @app.middleware("http")
    async def isolation_boundary(request,call_next):
        path=request.url.path
        if request.method not in {"GET","HEAD","OPTIONS"} and (
            path.startswith(("/api/desktop","/api/jobs","/api/imports","/api/extension"))
            or path.startswith("/api/settings/chatgpt/")
            or (path.startswith("/api/settings/provider") and not path.endswith("/test"))
            or (path.startswith("/api/settings/brave") and not path.endswith("/test"))
        ):
            return JSONResponse({"detail":"Audit harness blocks credential writes and external actions in this isolated UI."},status_code=403)
        return await call_next(request)
    import uvicorn
    uvicorn.run(app,host="127.0.0.1",port=4329,log_level="warning")
