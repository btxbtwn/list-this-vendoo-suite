from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def render_icon(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    pad = max(1, size // 16)
    radius = max(2, size // 5)
    draw.rounded_rectangle(
        (pad, pad, size - pad - 1, size - pad - 1),
        radius=radius,
        fill=(9, 9, 9, 255),
    )
    inner = pad + max(2, size // 8)
    draw.rounded_rectangle(
        (inner, inner, size - inner - 1, size - inner - 1),
        radius=max(2, size // 10),
        fill=(17, 17, 17, 255),
        outline=(52, 107, 241, 255),
        width=max(1, size // 32),
    )
    line_left = inner + max(2, size // 8)
    line_right = size - inner - 1 - max(2, size // 8)
    y = inner + max(3, size // 6)
    gap = max(3, size // 8)
    for index in range(3):
        draw.rectangle((line_left, y, line_right, y + max(2, size // 28)), fill=(226, 227, 229, 255))
        if index < 2:
            draw.rectangle(
                (line_left, y, line_left + max(2, size // 14), y + max(2, size // 28)),
                fill=(52, 107, 241, 255),
            )
        y += gap
    alpha = ImageChops.multiply(image.getchannel("A"), _rounded_mask(size, radius))
    image.putalpha(alpha)
    return image


def write_icns(destination: Path) -> Path:
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as raw:
        iconset = Path(raw) / "AppIcon.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            render_icon(size).save(iconset / f"icon_{size}x{size}.png")
            render_icon(size * 2).save(iconset / f"icon_{size}x{size}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", "-o", str(destination), str(iconset)], check=True)
    return destination


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("AppIcon.icns")
    write_icns(target)
    print(target)
