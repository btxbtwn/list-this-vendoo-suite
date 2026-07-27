from __future__ import annotations

import io
import re
import threading
import warnings
from dataclasses import dataclass
from typing import Iterable

from PIL import (
    Image,
    ImageChops,
    ImageDraw,
    ImageFilter,
    ImageOps,
    UnidentifiedImageError,
)

ALLOWED_FORMATS = {"JPEG", "MPO", "PNG", "WEBP"}
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
MIN_STROKE_POINTS = 2
MAX_STROKE_POINTS = 2048
MIN_STROKE_RADIUS = 0.0001
MAX_STROKE_RADIUS = 1.0
MAX_STROKES_PER_JOB = 512
_STROKE_SUPERSAMPLE = 4
_DECODE_LOCK = threading.Lock()


class ImageValidationError(ValueError):
    pass


@dataclass(frozen=True)
class RenderOptions:
    threshold: float
    feather: float
    background: str


def probe_upload(data: bytes, max_pixels: int) -> tuple[int, int]:
    """Validate metadata and return dimensions without decoding pixels."""
    if not data:
        raise ImageValidationError("The upload is empty.")
    with _DECODE_LOCK:
        previous_limit = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = max_pixels
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as source:
                    if source.format not in ALLOWED_FORMATS:
                        raise ImageValidationError(
                            "Only JPEG, PNG, and WebP images are accepted."
                        )
                    if source.format != "MPO" and (
                        bool(getattr(source, "is_animated", False))
                        or int(getattr(source, "n_frames", 1)) != 1
                    ):
                        raise ImageValidationError("Animated images are not accepted.")
                    width, height = source.size
                    if width < 1 or height < 1 or width * height > max_pixels:
                        raise ImageValidationError(
                            f"The image exceeds the {max_pixels:,}-pixel limit."
                        )
                    return width, height
        except (UnidentifiedImageError, OSError, SyntaxError) as exc:
            raise ImageValidationError(
                "The file is not a valid JPEG, PNG, or WebP image."
            ) from exc
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ImageValidationError(
                f"The image exceeds the {max_pixels:,}-pixel limit."
            ) from exc
        finally:
            Image.MAX_IMAGE_PIXELS = previous_limit


@dataclass(frozen=True)
class MaskStroke:
    mode: str
    radius: float
    softness: float
    points: tuple[tuple[float, float], ...]


def decode_upload(data: bytes, max_pixels: int) -> Image.Image:
    if not data:
        raise ImageValidationError("The upload is empty.")

    with _DECODE_LOCK:
        previous_limit = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = max_pixels
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as source:
                    if source.format not in ALLOWED_FORMATS:
                        raise ImageValidationError(
                            "Only JPEG, PNG, and WebP images are accepted."
                        )
                    if (
                        source.format != "MPO"
                        and (
                            bool(getattr(source, "is_animated", False))
                            or int(getattr(source, "n_frames", 1)) != 1
                        )
                    ):
                        raise ImageValidationError(
                            "Animated images are not accepted."
                        )

                    width, height = source.size
                    if (
                        width < 1
                        or height < 1
                        or width * height > max_pixels
                    ):
                        raise ImageValidationError(
                            f"The image exceeds the {max_pixels:,}-pixel limit."
                        )

                    source.seek(0)
                    source.load()
                    oriented = ImageOps.exif_transpose(source)

                    if oriented.width * oriented.height > max_pixels:
                        raise ImageValidationError(
                            f"The image exceeds the {max_pixels:,}-pixel limit."
                        )

                    decoded = oriented.convert("RGB")
                    decoded.info.clear()
                    return decoded
        except (UnidentifiedImageError, OSError, SyntaxError) as exc:
            raise ImageValidationError(
                "The file is not a valid JPEG, PNG, or WebP image."
            ) from exc
        except (
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as exc:
            raise ImageValidationError(
                f"The image exceeds the {max_pixels:,}-pixel limit."
            ) from exc
        finally:
            Image.MAX_IMAGE_PIXELS = previous_limit


def normalize_mask(
    mask: Image.Image,
    size: tuple[int, int],
) -> Image.Image:
    normalized = mask.convert("L")
    if normalized.size != size:
        normalized = normalized.resize(
            size,
            Image.Resampling.LANCZOS,
        )
    return normalized


def derive_alpha(
    raw_mask: Image.Image,
    threshold: float,
    feather: float,
) -> Image.Image:
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be between 0 and 1")
    if not 0.0 <= feather <= 64.0:
        raise ValueError("feather must be between 0 and 64")

    alpha = raw_mask.copy()

    if threshold > 0:
        cutoff = round(threshold * 255)
        alpha = alpha.point(
            [0 if value < cutoff else 255 for value in range(256)]
        )

    if feather > 0:
        alpha = alpha.filter(
            ImageFilter.GaussianBlur(radius=feather)
        )

    return alpha


def _stroke_coverage(
    size: tuple[int, int],
    stroke: MaskStroke,
) -> Image.Image:
    width, height = size
    scale = _STROKE_SUPERSAMPLE
    scaled_size = (
        max(1, width * scale),
        max(1, height * scale),
    )
    coverage = Image.new(
        "L",
        scaled_size,
        0,
    )
    draw = ImageDraw.Draw(coverage)
    radius = max(
        0.5,
        stroke.radius * min(width, height),
    ) * scale
    points = [
        (
            round(
                x
                * max(0, width - 1)
                * scale
            ),
            round(
                y
                * max(0, height - 1)
                * scale
            ),
        )
        for x, y in stroke.points
    ]
    line_width = max(
        1,
        round(radius * 2),
    )

    draw.line(
        points,
        fill=255,
        width=line_width,
        joint="curve",
    )

    for x, y in points:
        draw.ellipse(
            (
                round(x - radius),
                round(y - radius),
                round(x + radius),
                round(y + radius),
            ),
            fill=255,
        )

    if stroke.softness > 0:
        coverage = coverage.filter(
            ImageFilter.GaussianBlur(
                radius=max(
                    0.5,
                    radius
                    * stroke.softness
                    / 2,
                )
            )
        )

    return coverage.resize(
        size,
        Image.Resampling.LANCZOS,
    )


def apply_strokes(
    alpha: Image.Image,
    strokes: Iterable[MaskStroke],
) -> Image.Image:
    corrected = alpha.convert("L")

    for stroke in strokes:
        coverage = _stroke_coverage(
            corrected.size,
            stroke,
        )

        if stroke.mode == "remove":
            corrected = ImageChops.multiply(
                corrected,
                ImageOps.invert(coverage),
            )
        elif stroke.mode == "restore":
            corrected = ImageChops.screen(
                corrected,
                coverage,
            )
        else:
            raise ValueError(
                "stroke mode must be remove or restore"
            )

    return corrected


def parse_background(
    value: str,
) -> tuple[int, int, int] | None:
    if value == "transparent":
        return None

    if not HEX_RE.fullmatch(value):
        raise ValueError(
            "background must be transparent or a six-digit hex color"
        )

    return tuple(
        int(value[index:index + 2], 16)
        for index in (1, 3, 5)
    )


def compose(
    original: Image.Image,
    alpha: Image.Image,
    background: str,
) -> Image.Image:
    rgb = parse_background(background)
    foreground = original.convert("RGBA")
    foreground.putalpha(alpha)

    if rgb is None:
        return foreground

    base = Image.new(
        "RGBA",
        original.size,
        (*rgb, 255),
    )
    return Image.alpha_composite(
        base,
        foreground,
    ).convert("RGB")


def encode_image(
    image: Image.Image,
    fmt: str,
    filename: str | None = None,
) -> tuple[bytes, str, str]:
    normalized = fmt.lower()
    output = io.BytesIO()

    if normalized == "png":
        image.save(
            output,
            format="PNG",
            optimize=True,
        )
        media_type = "image/png"
        suffix = "png"
    elif normalized in {"jpg", "jpeg"}:
        if image.mode != "RGB":
            raise ValueError(
                "JPEG export requires a solid background"
            )
        image.save(
            output,
            format="JPEG",
            quality=95,
            optimize=True,
            subsampling=0,
        )
        media_type = "image/jpeg"
        suffix = "jpg"
    else:
        raise ValueError("format must be png or jpeg")

    name = filename or f"background-studio.{suffix}"
    return output.getvalue(), media_type, name


def make_preview(
    image: Image.Image,
    max_side: int,
) -> Image.Image:
    preview = image.copy()
    preview.thumbnail(
        (max_side, max_side),
        Image.Resampling.LANCZOS,
    )
    return preview
