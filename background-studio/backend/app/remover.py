from __future__ import annotations

import re
import threading
from typing import Protocol

from PIL import Image

MODEL_ID = "ZhengPeng7/BiRefNet_HR"
MODEL_REVISION = "707a63fd375513cc01cddd3c4e6125a184157f35"


def letterbox(
    image: Image.Image,
    size: int,
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    scale = min(
        size / image.width,
        size / image.height,
    )
    width = max(
        1,
        round(image.width * scale),
    )
    height = max(
        1,
        round(image.height * scale),
    )

    resized = image.resize(
        (width, height),
        Image.Resampling.LANCZOS,
    )
    left = (size - width) // 2
    top = (size - height) // 2

    canvas = Image.new(
        "RGB",
        (size, size),
        (0, 0, 0),
    )
    canvas.paste(
        resized,
        (left, top),
    )
    return canvas, (left, top, width, height)


class Remover(Protocol):
    def remove(self, image: Image.Image) -> Image.Image:
        raise NotImplementedError


class InferenceService:
    def __init__(self, remover: Remover) -> None:
        self._remover = remover
        self._lock = threading.Lock()

    def remove(self, image: Image.Image, generation_is_valid=None) -> Image.Image:
        with self._lock:
            if generation_is_valid is not None and not generation_is_valid():
                from asyncio import CancelledError
                raise CancelledError("Job creation was cancelled.")
            return self._remover.remove(image)


class BiRefNetHRRemover:
    def __init__(self) -> None:
        self._model = None
        self._torch = None
        self._np = None
        self._device = None
        self._mps_disabled = False
        self._normalization_constants = {}
        # A 2048px first pass can monopolize Apple Silicon for tens of minutes.
        # Start at 1024px so local interactive requests complete predictably.
        self._mps_size = 1024

    def _load_dependencies(self):
        if self._torch is None:
            import numpy as np
            import torch
            from transformers import AutoModelForImageSegmentation

            model = (
                AutoModelForImageSegmentation
                .from_pretrained(
                    MODEL_ID,
                    revision=MODEL_REVISION,
                    trust_remote_code=True,
                )
                .eval()
            )
            self._torch, self._np, self._model = torch, np, model

        return self._torch, self._np

    def _move_model(self, device: str) -> None:
        if self._device != device:
            self._model = self._model.to(device)
            self._device = device

    @staticmethod
    def _letterbox(
        image: Image.Image,
        size: int,
    ) -> tuple[Image.Image, tuple[int, int, int, int]]:
        return letterbox(image, size)

    def _normalization_tensors(self, torch, tensor):
        key = (str(tensor.device), tensor.dtype)
        constants = self._normalization_constants.get(key)
        if constants is None:
            constants = (
                torch.tensor(
                    [0.485, 0.456, 0.406],
                    device=tensor.device,
                    dtype=tensor.dtype,
                ).view(1, 3, 1, 1),
                torch.tensor(
                    [0.229, 0.224, 0.225],
                    device=tensor.device,
                    dtype=tensor.dtype,
                ).view(1, 3, 1, 1),
            )
            self._normalization_constants[key] = constants
        return constants

    @staticmethod
    def _prediction_tensor(output):
        if hasattr(output, "logits"):
            output = output.logits
        elif isinstance(output, dict):
            output = output.get(
                "logits",
                list(output.values())[-1],
            )

        if isinstance(output, (list, tuple)):
            output = output[-1]
        if isinstance(output, (list, tuple)):
            output = output[-1]

        return output

    def _infer(
        self,
        image: Image.Image,
        size: int,
        device: str,
    ) -> Image.Image:
        torch, np = self._load_dependencies()
        self._move_model(device)

        canvas, (
            left,
            top,
            width,
            height,
        ) = self._letterbox(image, size)

        array = (
            np.asarray(
                canvas,
                dtype=np.float32,
            )
            / 255.0
        )

        tensor = (
            torch.from_numpy(array)
            .permute(2, 0, 1)
            .unsqueeze(0)
        )

        mean, std = self._normalization_tensors(
            torch,
            tensor,
        )

        tensor = (
            (tensor - mean)
            / std
        ).to(device)

        with torch.inference_mode():
            prediction = self._prediction_tensor(
                self._model(tensor)
            ).sigmoid()

        prediction = (
            prediction
            .squeeze()
            .detach()
            .float()
            .cpu()
            .numpy()
        )
        prediction = np.clip(
            prediction,
            0.0,
            1.0,
        )

        square = Image.fromarray(
            (
                prediction * 255.0
            )
            .round()
            .astype("uint8"),
            mode="L",
        )

        if square.size != (size, size):
            square = square.resize(
                (size, size),
                Image.Resampling.BILINEAR,
            )

        cropped = square.crop(
            (
                left,
                top,
                left + width,
                top + height,
            )
        )

        return cropped.resize(
            image.size,
            Image.Resampling.LANCZOS,
        )

    @staticmethod
    def _is_mps_memory_error(
        exc: RuntimeError,
    ) -> bool:
        message = str(exc).lower()
        if re.fullmatch(
            r"(?:(?:mps backend|mps allocator):\s*|mps\s+)?"
            r"invalid buffer size:\s*"
            r"\d+(?:\.\d+)?\s*"
            r"(?:bytes?|kb|mb|gb|tb|kib|mib|gib|tib)",
            message,
        ):
            return True
        if "mps" not in message:
            return False
        return any(fragment in message for fragment in (
            "mps backend out of memory",
            "mps out of memory",
            "mps backend ran out of memory",
        ))

    @staticmethod
    def _is_mps_unsupported_error(
        exc: BaseException,
    ) -> bool:
        # Known PyTorch diagnostics may wrap across lines. Normalize whitespace
        # while retaining the narrow anchored prefixes and advisory checks.
        message = re.sub(r"\s+", " ", str(exc).strip().lower())
        operator_match = re.fullmatch(
            r"the operator ['\"][^'\"]+['\"] is (?:not currently |not )?implemented for (?:the )?mps device\.?(?P<advisory>.*)",
            message,
        )
        missing_operator = False
        if operator_match:
            advisory = operator_match.group("advisory").strip()
            missing_operator = not advisory or (
                advisory.startswith("if you want this op to be added in priority during the prototype phase of this feature")
                and "github.com/pytorch/pytorch/issues/77764" in advisory
                and "pytorch_enable_mps_fallback=1" in advisory
            )
        newer_operator_advisory = re.fullmatch(
            r"the operator ['\"][^'\"]+['\"] is (?:not currently |not )?"
            r"implemented for (?:the )?mps device\.? "
            r"if you want this op to be considered for addition please comment on "
            r"https://github\.com/pytorch/pytorch/issues/141287 and mention "
            r"use-case, that resulted in missing op as well as commit hash "
            r"[0-9a-f]{40}\. as a temporary fix, you can set the environment "
            r"variable [`'\"]?pytorch_enable_mps_fallback=1[`'\"]? to use the cpu "
            r"as a fallback for this op\. warning: this will be slower than running "
            r"natively on mps\.?",
            message,
        )
        missing_dispatch = re.fullmatch(
            r"could not run ['\"][^'\"]+['\"] with arguments from the ['\"]mps['\"] backend(?:\..*)?",
            message,
        )
        return bool(missing_operator or newer_operator_advisory or missing_dispatch)

    @staticmethod
    def _empty_mps_cache(torch) -> None:
        empty_cache = getattr(
            getattr(torch, "mps", None),
            "empty_cache",
            None,
        )
        if callable(empty_cache):
            try:
                empty_cache()
            except RuntimeError:
                pass

    def remove(
        self,
        image: Image.Image,
    ) -> Image.Image:
        torch, _ = self._load_dependencies()

        mps_available = bool(
            getattr(
                torch.backends,
                "mps",
                None,
            )
            and torch.backends.mps.is_available()
        )

        if mps_available and not self._mps_disabled:
            sizes = [
                size
                for size in (2048, 1536, 1024, 768, 512)
                if size <= self._mps_size
            ]

            for size in sizes:
                try:
                    result = self._infer(
                        image,
                        size,
                        "mps",
                    )
                    self._mps_size = size
                    return result
                except (RuntimeError, NotImplementedError) as exc:
                    if self._is_mps_memory_error(exc):
                        lower_sizes = [candidate for candidate in sizes if candidate < size]
                        if lower_sizes:
                            self._mps_size = lower_sizes[0]
                        self._empty_mps_cache(torch)
                        continue
                    if self._is_mps_unsupported_error(exc):
                        self._mps_disabled = True
                        self._empty_mps_cache(torch)
                        break
                    raise

        return self._infer(
            image,
            1024,
            "cpu",
        )
