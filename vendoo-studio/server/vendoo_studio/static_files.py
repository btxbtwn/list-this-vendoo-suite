"""Serve the built interface so a browser always picks up a new build.

The bundle's chunks carry a content hash in their names, so they can be cached
for as long as a browser likes. ``index.html`` and the build stamp are what
name those chunks, so they must be revalidated on every load: without a
Cache-Control header a browser is free to keep them for days, and a phone that
opened Studio before an update went on showing the old interface against the
new backend.
"""
from __future__ import annotations

import os
from pathlib import PurePath

from starlette.staticfiles import PathLike, StaticFiles
from starlette.types import Scope

REVALIDATE = "no-cache"
IMMUTABLE = "public, max-age=31536000, immutable"


def cache_control(path: str) -> str:
    """The Cache-Control for a file in ``dist/``: hashed assets never change
    under their name; everything else is checked with the server each load."""
    parts = PurePath(path).parts
    return IMMUTABLE if parts and parts[0] == "assets" else REVALIDATE


class FrontendFiles(StaticFiles):
    def file_response(self, full_path: PathLike, stat_result: os.stat_result, scope: Scope, status_code: int = 200):
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Cache-Control"] = cache_control(os.path.relpath(full_path, self.directory))
        return response
