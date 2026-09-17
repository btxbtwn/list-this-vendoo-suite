from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from vendoo_studio.config import HOST, PORT, CORS_ORIGINS, frontend_dist_dir
from vendoo_studio.database import init_db
from vendoo_studio.routes import health, conversations, photos, listings, jobs, settings, extension, chat, updates, desktop, imports
from vendoo_studio.routes import catalog


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        from vendoo_studio.services.keychain import warm_keychain
        warm_keychain()
    except Exception:
        pass
    try:
        from vendoo_studio.services.category_tree_seed import ensure_seeded_category_trees
        ensure_seeded_category_trees()
    except Exception:
        pass
    try:
        from vendoo_studio.database import SessionLocal
        from vendoo_studio.services.catalog_index import ensure_catalog_index
        import threading

        def _build_catalog_index() -> None:
            try:
                with SessionLocal() as db:
                    ensure_catalog_index(db)
            except Exception:
                pass

        threading.Thread(target=_build_catalog_index, name="catalog-index", daemon=True).start()
    except Exception:
        pass
    try:
        from vendoo_studio.services.chrome_bridge import install_bundled_extension
        install_bundled_extension()
    except Exception:
        pass
    yield


app = FastAPI(
    title="Vendoo Listing Studio",
    version="0.1.0",
    description="Local web app for generating and automating Vendoo marketplace listings",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)

app.include_router(health.router)
app.include_router(conversations.router)
app.include_router(photos.router)
app.include_router(listings.router)
app.include_router(jobs.router)
app.include_router(imports.router)
app.include_router(settings.router)
app.include_router(extension.router)
app.include_router(chat.router)
app.include_router(catalog.router)
app.include_router(updates.router)
app.include_router(desktop.router)

dist_dir = frontend_dist_dir()
if dist_dir.exists():
    app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="static")


def main():
    import uvicorn
    uvicorn.run(
        "vendoo_studio.main:app",
        host=HOST,
        port=PORT,
        reload=os.environ.get("VENDOO_STUDIO_DEV", "") == "1",
    )


if __name__ == "__main__":
    main()
