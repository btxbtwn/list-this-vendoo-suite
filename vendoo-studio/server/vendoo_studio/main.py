from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from vendoo_studio.config import HOST, PORT, CORS_ORIGINS, frontend_dist_dir
from vendoo_studio.database import init_db
from vendoo_studio.routes import health, conversations, photos, listings, jobs, settings, extension, chat, updates, desktop


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(conversations.router)
app.include_router(photos.router)
app.include_router(listings.router)
app.include_router(jobs.router)
app.include_router(settings.router)
app.include_router(extension.router)
app.include_router(chat.router)
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
