"""Read extension sources the way Chrome loads them."""

from __future__ import annotations

import re
from pathlib import Path

EXTENSION_DIR = Path(__file__).resolve().parents[3] / "vendoo-extension"


def background_source() -> str:
    """background.js plus every script it pulls in from background/, in load order."""
    main = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
    parts = [main]
    for rel in re.findall(r"importScripts\('(background/[^']+)'\)", main):
        parts.append((EXTENSION_DIR / rel).read_text(encoding="utf-8"))
    return "\n".join(parts)
