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
    original: Image.Image | None = None,
) -> Image.Image:
    corrected = alpha.convert("L")
    guide = (
        original.convert("RGB")
        if original is not None
        else None
    )

    for stroke in strokes:
        coverage = _stroke_coverage(
            corrected.size,
            stroke,
        )

        if stroke.mode == "remove":
            if guide is not None:
                coverage = _guided_stroke_coverage(
                    guide,
                    ImageOps.invert(corrected),
                    coverage,
                    stroke,
                )
            corrected = ImageChops.multiply(
                corrected,
                ImageOps.invert(coverage),
            )
        elif stroke.mode == "restore":
            if guide is not None:
                coverage = _guided_stroke_coverage(
                    guide,
                    corrected,
                    coverage,
                    stroke,
                )
            corrected = ImageChops.screen(
                corrected,
                coverage,
            )
        else:
            raise ValueError(
                "stroke mode must be remove or restore"
            )

    return corrected


def _guided_stroke_coverage(
    original: Image.Image,
    alpha: Image.Image,
    coverage: Image.Image,
    stroke: MaskStroke,
) -> Image.Image:
    """Expand stroke hints within the positive side of visible edges."""
    if min(coverage.size) < 512:
        literal_coverage = coverage.point(
            [
                0 if value < 64 else 255
                for value in range(256)
            ]
        ).filter(
            ImageFilter.GaussianBlur(
                radius=0.5
            )
        )
    else:
        # Keep the supersampled antialiasing produced by _stroke_coverage. A
        # binary threshold here turns a high-resolution finger path into a
        # visibly stair-stepped contour when it is exported at source size.
        literal_coverage = coverage.filter(
            ImageFilter.GaussianBlur(
                radius=0.6
            )
        )

    try:
        import cv2
        import numpy as np
    except ImportError:
        return literal_coverage

    width, height = coverage.size
    assisted_stroke = MaskStroke(
        mode=stroke.mode,
        radius=min(
            MAX_STROKE_RADIUS,
            stroke.radius * 2.0,
        ),
        softness=0.0,
        points=stroke.points,
    )
    assisted_coverage = _stroke_coverage(
        coverage.size,
        assisted_stroke,
    )
    bounds = assisted_coverage.getbbox()
    if bounds is None:
        return literal_coverage

    left = max(0, bounds[0] - 2)
    top = max(0, bounds[1] - 2)
    right = min(width, bounds[2] + 2)
    bottom = min(height, bounds[3] + 2)
    crop_box = (left, top, right, bottom)

    brush = np.asarray(
        coverage.crop(crop_box),
        dtype=np.uint8,
    )
    assisted_brush = np.asarray(
        assisted_coverage.crop(
            crop_box
        ),
        dtype=np.uint8,
    )
    current_alpha = np.asarray(
        alpha.crop(crop_box),
        dtype=np.uint8,
    )
    rgb = np.asarray(
        original.crop(crop_box),
        dtype=np.uint8,
    )

    crop_height, crop_width = brush.shape
    if crop_width < 3 or crop_height < 3:
        return literal_coverage

    core_stroke = MaskStroke(
        mode=stroke.mode,
        radius=max(
            MIN_STROKE_RADIUS,
            1.5 / min(width, height),
        ),
        softness=0.0,
        points=stroke.points,
    )
    core = np.asarray(
        _stroke_coverage(
            coverage.size,
            core_stroke,
        ).crop(crop_box),
        dtype=np.uint8,
    )
    # The stroke path is the only authoritative seed.  Treating every
    # already-visible/transparent pixel inside the expanded brush as another
    # seed turns fabric texture and stray mask islands into separate regions;
    # the connected-component pass then returns a speckled brush instead of
    # one protected region.  Existing alpha is still used as a guide below,
    # but it must not create new seeds away from the user's stroke.
    foreground_seed = (
        (core >= 128)
        & (assisted_brush > 2)
    )
    if not np.any(foreground_seed):
        return literal_coverage

    blurred = cv2.GaussianBlur(
        rgb,
        (7, 7),
        0,
    )
    lab = cv2.cvtColor(
        blurred,
        cv2.COLOR_RGB2LAB,
    )
    prototype_seed = foreground_seed
    seed_colors = lab[
        prototype_seed
    ]
    if seed_colors.size == 0:
        return literal_coverage

    def dominant_prototypes(colors):
        quantized = (
            colors.astype(
                np.uint16
            )
            // 24
        )
        color_codes = (
            quantized[:, 0] * 121
            + quantized[:, 1] * 11
            + quantized[:, 2]
        )
        (
            unique_codes,
            inverse,
            counts,
        ) = np.unique(
            color_codes,
            return_inverse=True,
            return_counts=True,
        )
        dominant = np.argsort(
            counts
        )[
            -min(
                8,
                unique_codes.size,
            ):
        ]
        return np.stack(
            [
                np.median(
                    colors[
                        inverse == index
                    ],
                    axis=0,
                )
                for index in dominant
            ]
        ).astype(np.int32)

    prototypes = dominant_prototypes(
        seed_colors
    )
    lab_values = lab.astype(
        np.int32
    )
    color_distance = np.full(
        lab.shape[:2],
        np.iinfo(np.int32).max,
        dtype=np.int32,
    )
    for prototype in prototypes:
        difference = (
            lab_values
            - prototype
        )
        distance = np.sum(
            difference * difference,
            axis=2,
            dtype=np.int32,
        )
        color_distance = np.minimum(
            color_distance,
            distance,
        )
    color_match = (
        color_distance
        <= 42 * 42
    )
    assist_allowed = True
    if np.any(
        current_alpha >= 192
    ):
        background_seed = (
            (current_alpha < 32)
            & (assisted_brush > 2)
            & (core < 128)
        )
        background_colors = lab[
            background_seed
        ]
        if background_colors.size > 0:
            background_prototypes = (
                dominant_prototypes(
                    background_colors
                )
            )
            separation = (
                prototypes[:, None, :]
                - background_prototypes[
                    None,
                    :,
                    :,
                ]
            )
            minimum_separation = np.min(
                np.sum(
                    separation
                    * separation,
                    axis=2,
                    dtype=np.int32,
                )
            )
            assist_allowed = (
                minimum_separation
                > 28 * 28
            )
    edges = np.zeros(
        brush.shape,
        dtype=np.uint8,
    )
    for channel in cv2.split(lab):
        edges = cv2.bitwise_or(
            edges,
            cv2.Canny(
                channel,
                20,
                50,
            ),
        )
    edges = cv2.morphologyEx(
        edges,
        cv2.MORPH_CLOSE,
        np.ones(
            (3, 3),
            dtype=np.uint8,
        ),
    )
    candidate_brush = (
        assisted_brush
        if assist_allowed
        else brush
    )
    inside_brush = (
        candidate_brush > 2
    )
    active_seed = (
        foreground_seed
        & inside_brush
    )
    edge_pixels = (
        (edges > 0)
        & inside_brush
    )
    if not np.any(edge_pixels):
        return literal_coverage

    brush_boundary = (
        inside_brush
        & (
            cv2.erode(
                inside_brush.astype(
                    np.uint8
                ),
                np.ones(
                    (3, 3),
                    dtype=np.uint8,
                ),
                iterations=1,
            )
            == 0
        )
    )
    brush_boundary[0, :] = (
        inside_brush[0, :]
    )
    brush_boundary[-1, :] = (
        inside_brush[-1, :]
    )
    brush_boundary[:, 0] = (
        inside_brush[:, 0]
    )
    brush_boundary[:, -1] = (
        inside_brush[:, -1]
    )
    edge_count, edge_labels = (
        cv2.connectedComponents(
            edge_pixels.astype(
                np.uint8
            ),
            connectivity=8,
        )
    )
    boundary_edge_labels = np.unique(
        edge_labels[brush_boundary]
    )
    boundary_edge_labels = (
        boundary_edge_labels[
            boundary_edge_labels != 0
        ]
    )
    if stroke.mode == "restore":
        long_boundary_labels = []
        for label in boundary_edge_labels:
            edge_y, edge_x = np.where(
                edge_labels == label
            )
            if edge_x.size > 0 and (
                edge_x.max() - edge_x.min() + 1
                >= max(
                    3,
                    round(
                        crop_width
                        * 0.55
                    ),
                )
                or edge_y.max() - edge_y.min() + 1
                >= max(
                    3,
                    round(
                        crop_height
                        * 0.55
                    ),
                )
            ):
                long_boundary_labels.append(label)
        boundary_edge_labels = np.asarray(
            long_boundary_labels,
            dtype=np.int32,
        )

        # Once part of a garment is already visible, only a real alpha
        # transition should be allowed to fence the restore stroke. Texture
        # and print edges can be long too, but they do not separate visible
        # foreground from transparent background. Without this check they
        # turn a solid shirt restore into a field of tiny islands.
        if np.any(current_alpha >= 192):
            foreground = current_alpha >= 192
            background = current_alpha < 32
            kernel = np.ones(
                (3, 3),
                dtype=np.uint8,
            )
            alpha_transition = (
                cv2.dilate(
                    foreground.astype(np.uint8),
                    kernel,
                    iterations=1,
                )
                & cv2.dilate(
                    background.astype(np.uint8),
                    kernel,
                    iterations=1,
                )
            )
            alpha_transition = cv2.dilate(
                alpha_transition.astype(np.uint8),
                kernel,
                iterations=1,
            ) > 0
            boundary_edge_labels = np.asarray(
                [
                    label
                    for label in boundary_edge_labels
                    if np.any(
                        alpha_transition
                        & (edge_labels == label)
                    )
                ],
                dtype=np.int32,
            )
    if (
        edge_count <= 1
        or boundary_edge_labels.size == 0
    ):
        return literal_coverage

    barrier = np.isin(
        edge_labels,
        boundary_edge_labels,
    )
    allowed_foreground = (
        np.ones(
            brush.shape,
            dtype=bool,
        )
        if stroke.mode == "restore"
        else (
            color_match
            | (current_alpha >= 64)
            | (brush > 2)
        )
    )
    walkable = (
        inside_brush
        & ~barrier
        & allowed_foreground
    )
    walkable[active_seed] = True
    _, labels = cv2.connectedComponents(
        walkable.astype(np.uint8),
        connectivity=4,
    )
    seed_labels = np.unique(
        labels[active_seed]
    )
    seed_labels = seed_labels[
        seed_labels != 0
    ]
    if seed_labels.size == 0:
        return literal_coverage

    inferred_foreground = np.isin(
        labels,
        seed_labels,
    )
    inferred_foreground = cv2.dilate(
        inferred_foreground.astype(
            np.uint8
        ),
        np.ones(
            (3, 3),
            dtype=np.uint8,
        ),
        iterations=1,
    ).astype(bool)
    inferred_foreground = (
        cv2.morphologyEx(
            inferred_foreground.astype(
                np.uint8
            ),
            cv2.MORPH_CLOSE,
            np.ones(
                (3, 3),
                dtype=np.uint8,
            ),
            iterations=1,
        )
        > 0
    )
    selected_area = np.count_nonzero(
        inferred_foreground
        & inside_brush
    )
    brush_area = np.count_nonzero(
        inside_brush
    )
    if (
        brush_area > 0
        and selected_area / brush_area < 0.2
    ):
        return literal_coverage

    guided_brush = np.where(
        inferred_foreground
        & inside_brush,
        255,
        0,
    ).astype(np.uint8)
    # The inferred region is binary, but the source image is not. Close tiny
    # gaps caused by fabric texture, then restore a narrow antialiased edge so
    # the guided path does not export as a pixelated outline.
    if min(coverage.size) >= 512:
        guided_brush = cv2.morphologyEx(
            guided_brush,
            cv2.MORPH_CLOSE,
            np.ones((3, 3), dtype=np.uint8),
        )
        guided_brush = cv2.GaussianBlur(
            guided_brush,
            (0, 0),
            sigmaX=1.2,
        )

    result = Image.new(
        "L",
        coverage.size,
        0,
    )
    result.paste(
        Image.fromarray(
            guided_brush,
            mode="L",
        ),
        (left, top),
    )
    return result


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
