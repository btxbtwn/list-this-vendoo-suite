"""Current built UI with a simulated connected-but-outdated extension status."""
import os
import tempfile
from unittest.mock import patch

with tempfile.TemporaryDirectory(prefix="vendoo-outdated-ui-") as tmp:
    os.environ["VENDOO_STUDIO_DATA_DIR"]=tmp
    from fastapi.responses import JSONResponse
    from vendoo_studio.main import app
    from vendoo_studio.routes.extension import extension_manager
    extension_manager.connection=object()
    extension_manager.paired=True
    extension_manager.version="0.0.1-audit"
    extension_manager.build="outdated-audit-build"
    extension_manager.reload_generation="audit-old"
    @app.middleware("http")
    async def isolation_boundary(request,call_next):
        if request.method not in {"GET","HEAD","OPTIONS"}:
            return JSONResponse({"detail":"Audit harness blocks external actions in this isolated UI."},status_code=403)
        return await call_next(request)
    with patch("vendoo_studio.services.chrome_bridge.install_bundled_extension",return_value=None):
        import uvicorn
        uvicorn.run(app,host="127.0.0.1",port=4330,log_level="warning")
