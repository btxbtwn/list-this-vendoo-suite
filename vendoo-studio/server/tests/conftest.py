from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest


def pytest_configure(config):
    """Give each xdist worker its own data dir before vendoo_studio.config is imported."""
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker:
        return
    base = Path(os.environ.get("VENDOO_STUDIO_DATA_DIR") or tempfile.mkdtemp(prefix="vendoo-studio-tests-"))
    worker_dir = base / worker
    worker_dir.mkdir(parents=True, exist_ok=True)
    os.environ["VENDOO_STUDIO_DATA_DIR"] = str(worker_dir)


@pytest.fixture(scope="session", autouse=True)
def _isolate_studio_settings(tmp_path_factory):
    previous = os.environ.get("VENDOO_STUDIO_DATA_DIR")
    root = tmp_path_factory.mktemp("studio-settings")
    os.environ["VENDOO_STUDIO_DATA_DIR"] = str(root)
    (root / "settings.json").write_text(json.dumps({
        "marketplaces": ["ebay", "poshmark", "mercari", "depop"],
    }) + "\n")
    # Code paths such as queue dispatch open the app's own SessionLocal. Create its
    # schema up front like app startup does, so results do not depend on test order.
    from vendoo_studio.database import init_db

    init_db()
    yield
    if previous is None:
        os.environ.pop("VENDOO_STUDIO_DATA_DIR", None)
    else:
        os.environ["VENDOO_STUDIO_DATA_DIR"] = previous
