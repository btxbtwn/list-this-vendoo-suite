"""Studio app version — single source of truth is ``vendoo-studio/VERSION``."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


def _candidates() -> list[Path]:
    paths: list[Path] = []
    # Editable / source tree: server/vendoo_studio → vendoo-studio/
    paths.append(Path(__file__).resolve().parents[2] / "VERSION")
    try:
        from vendoo_studio.config import resource_root

        root = resource_root()
        paths.append(root / "VERSION")
        paths.append(root / "build_info.json")
    except Exception:
        pass
    return paths


@lru_cache(maxsize=1)
def app_version() -> str:
    for path in _candidates():
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if path.name == "build_info.json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            version = str(payload.get("version") or "").strip()
            if version:
                return version
            continue
        if text:
            return text
    return "0.0.0"
