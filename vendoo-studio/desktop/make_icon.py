from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SOURCE_ICON = REPO_ROOT / "vendoo-extension" / "icons" / "icon128.png"
STUDIO_FAVICON = Path(__file__).resolve().parent.parent / "public" / "favicon.png"


def load_source_icon() -> Image.Image:
    if not SOURCE_ICON.is_file():
        raise FileNotFoundError(f"Chrome extension icon is missing: {SOURCE_ICON}")
    return Image.open(SOURCE_ICON).convert("RGBA")


def render_icon(size: int) -> Image.Image:
    source = load_source_icon()
    if source.size == (size, size):
        return source.copy()
    return source.resize((size, size), Image.Resampling.LANCZOS)


def write_icns(destination: Path) -> Path:
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    iconutil = shutil.which("iconutil")
    if iconutil is None:
        raise FileNotFoundError("iconutil is required to build a macOS .icns file")
    with tempfile.TemporaryDirectory() as raw:
        iconset = Path(raw) / "AppIcon.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            render_icon(size).save(iconset / f"icon_{size}x{size}.png")
            render_icon(size * 2).save(iconset / f"icon_{size}x{size}@2x.png")
        subprocess.run([iconutil, "-c", "icns", "-o", str(destination), str(iconset)], check=True)
    return destination


def write_favicon(destination: Path = STUDIO_FAVICON) -> Path:
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    render_icon(32).save(destination)
    return destination


if __name__ == "__main__":
    written: list[Path] = []
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "AppIcon.icns"
    if shutil.which("iconutil"):
        written.append(write_icns(destination))
    elif destination.suffix.lower() == ".icns":
        print(f"skip icns (iconutil not found): {destination}")
    written.append(write_favicon())
    for path in written:
        print(path)
