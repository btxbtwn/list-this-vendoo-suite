from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def _isolate_studio_settings(tmp_path_factory):
    previous = os.environ.get("VENDOO_STUDIO_DATA_DIR")
    root = tmp_path_factory.mktemp("studio-settings")
    os.environ["VENDOO_STUDIO_DATA_DIR"] = str(root)
    (root / "settings.json").write_text(json.dumps({
        "marketplaces": ["ebay", "poshmark", "mercari", "depop"],
    }) + "\n")
    yield
    if previous is None:
        os.environ.pop("VENDOO_STUDIO_DATA_DIR", None)
    else:
        os.environ["VENDOO_STUDIO_DATA_DIR"] = previous
