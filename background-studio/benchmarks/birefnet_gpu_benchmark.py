"""One-shot CUDA benchmark for the pinned BiRefNet-HR production model."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import statistics
import sys
import time
from typing import Any

MODEL_ID = "ZhengPeng7/BiRefNet_HR"
MODEL_REVISION = "707a63fd375513cc01cddd3c4e6125a184157f35"
INPUT_SIZE = 1024
DEFAULT_ITERATIONS = 5
BYTES_PER_MIB = 1024 * 1024
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


class BenchmarkError(RuntimeError):
    """An expected benchmark failure with a user-safe message."""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark the production BiRefNet-HR model on one CUDA GPU."
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=DEFAULT_ITERATIONS,
        help=f"Number of measured inference iterations (default: {DEFAULT_ITERATIONS}).",
    )
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be at least 1")
    return args


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _make_input(np: Any, torch: Any, image_type: Any, device: Any) -> Any:
    """Create a deterministic, synthetic, letterboxed production-size input."""
    source_width = INPUT_SIZE
    source_height = 768
    x = np.arange(source_width, dtype=np.uint32)[None, :]
    y = np.arange(source_height, dtype=np.uint32)[:, None]
    rgb = np.empty((source_height, source_width, 3), dtype=np.uint8)
    rgb[..., 0] = ((37 * x + 17 * y) & 0xFF).astype(np.uint8)
    rgb[..., 1] = ((x // 4) ^ (y // 4) ^ ((x + y) // 16)).astype(np.uint8)
    rgb[..., 2] = ((3 * x + 5 * y + (x * y) // 97) & 0xFF).astype(np.uint8)

    source = image_type.fromarray(rgb, mode="RGB")
    canvas = image_type.new("RGB", (INPUT_SIZE, INPUT_SIZE))
    offset_y = (INPUT_SIZE - source_height) // 2
    canvas.paste(source, (0, offset_y))

    array = np.asarray(canvas, dtype=np.float32) / 255.0
    tensor = torch.from_numpy(np.ascontiguousarray(array.transpose(2, 0, 1)))
    mean = torch.tensor(IMAGENET_MEAN, dtype=torch.float32).view(3, 1, 1)
    std = torch.tensor(IMAGENET_STD, dtype=torch.float32).view(3, 1, 1)
    normalized = ((tensor - mean) / std).unsqueeze(0)
    return normalized.to(device=device, dtype=torch.float32)


def _extract_prediction(output: Any, torch: Any) -> Any:
    """Normalize the model's supported output shapes into a sigmoid mask tensor."""
    if hasattr(output, "logits"):
        output = output.logits
    elif isinstance(output, dict):
        if "logits" in output:
            output = output["logits"]
        elif output:
            output = list(output.values())[-1]

    while isinstance(output, (list, tuple)) and output:
        output = output[-1]

    if not torch.is_tensor(output):
        raise BenchmarkError("Model output did not contain a tensor prediction.")
    return torch.sigmoid(output)


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * 0.95
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _benchmark(iterations: int) -> dict[str, Any]:
    import_started = time.perf_counter()
    try:
        import numpy as np
        import torch
        from PIL import Image
        from transformers import AutoModelForImageSegmentation
    except ImportError as exc:
        raise BenchmarkError(
            f"Missing benchmark dependency: {exc.name or type(exc).__name__}."
        ) from None
    dependency_import_seconds = time.perf_counter() - import_started

    if not torch.cuda.is_available():
        raise BenchmarkError("CUDA is not available; this benchmark requires one NVIDIA GPU.")

    device = torch.device("cuda:0")
    properties = torch.cuda.get_device_properties(device)
    _progress(f"Loading {MODEL_ID}@{MODEL_REVISION} on {properties.name}...")

    load_started = time.perf_counter()
    model = AutoModelForImageSegmentation.from_pretrained(
        MODEL_ID,
        revision=MODEL_REVISION,
        trust_remote_code=True,
    )
    model.eval()
    model.to(device=device, dtype=torch.float32)
    torch.cuda.synchronize(device)
    model_load_seconds = time.perf_counter() - load_started

    input_tensor = _make_input(np, torch, Image, device)
    _progress("Running one warmup inference...")
    torch.cuda.synchronize(device)
    warmup_started = time.perf_counter()
    with torch.inference_mode():
        warmup_output = _extract_prediction(model(input_tensor), torch)
    torch.cuda.synchronize(device)
    warmup_seconds = time.perf_counter() - warmup_started
    del warmup_output

    torch.cuda.reset_peak_memory_stats(device)
    inference_seconds: list[float] = []
    final_output = None
    _progress(f"Running {iterations} measured inference iterations...")
    with torch.inference_mode():
        for iteration in range(iterations):
            torch.cuda.synchronize(device)
            started = time.perf_counter()
            final_output = _extract_prediction(model(input_tensor), torch)
            torch.cuda.synchronize(device)
            elapsed = time.perf_counter() - started
            inference_seconds.append(elapsed)
            _progress(f"Iteration {iteration + 1}/{iterations}: {elapsed:.4f}s")

    peak_allocated_mib = torch.cuda.max_memory_allocated(device) / BYTES_PER_MIB
    peak_reserved_mib = torch.cuda.max_memory_reserved(device) / BYTES_PER_MIB

    if final_output is None:
        raise BenchmarkError("No inference output was produced.")
    output = final_output.detach().to(device="cpu", dtype=torch.float32).contiguous().numpy()
    if output.size == 0 or not np.isfinite(output).all():
        raise BenchmarkError("Model output was empty or contained non-finite values.")
    mask_bytes = np.rint(np.clip(output, 0.0, 1.0) * 255.0).astype(np.uint8).tobytes()

    return {
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "gpu_name": properties.name,
        "gpu_total_memory_mib": properties.total_memory / BYTES_PER_MIB,
        "iterations": iterations,
        "dependency_import_seconds": dependency_import_seconds,
        "model_load_seconds": model_load_seconds,
        "warmup_seconds": warmup_seconds,
        "inference_seconds": inference_seconds,
        "inference_mean_seconds": statistics.fmean(inference_seconds),
        "inference_median_seconds": statistics.median(inference_seconds),
        "inference_p95_seconds": _p95(inference_seconds),
        "inference_p95_method": "linear interpolation at (n - 1) * 0.95",
        "peak_allocated_mib": peak_allocated_mib,
        "peak_reserved_mib": peak_reserved_mib,
        "output_shape": list(output.shape),
        "output_min": float(output.min()),
        "output_max": float(output.max()),
        "output_sha256": hashlib.sha256(mask_bytes).hexdigest(),
    }


def main() -> int:
    args = _parse_args()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = _benchmark(args.iterations)
    except BenchmarkError as exc:
        print(f"Benchmark failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"Benchmark failed with unexpected {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
