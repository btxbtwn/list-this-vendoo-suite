from types import SimpleNamespace
import re

import pytest
from PIL import Image

from app.remover import BiRefNetHRRemover


class FakeMPS:
    def __init__(self):
        self.cache_clears = 0

    @staticmethod
    def is_available():
        return True

    def empty_cache(self):
        self.cache_clears += 1


def fake_torch():
    mps = FakeMPS()
    return SimpleNamespace(
        backends=SimpleNamespace(mps=mps),
        mps=mps,
    )


def configured_remover(monkeypatch):
    remover = BiRefNetHRRemover()
    torch = fake_torch()
    monkeypatch.setattr(
        remover,
        "_load_dependencies",
        lambda: (torch, None),
    )
    return remover, torch


def test_unsupported_mps_operator_falls_back_to_cpu(monkeypatch):
    remover, torch = configured_remover(monkeypatch)
    calls = []

    def infer(image, size, device):
        calls.append((size, device))
        if device == "mps":
            raise RuntimeError(
                "The operator 'torchvision::deform_conv2d' is not currently "
                "implemented for the MPS device."
            )
        return image

    monkeypatch.setattr(remover, "_infer", infer)
    image = Image.new("RGB", (8, 8))

    assert remover.remove(image) is image
    assert calls == [(1024, "mps"), (1024, "cpu")]
    assert remover._mps_disabled is True
    assert torch.mps.cache_clears == 1


def test_current_pytorch_mps_diagnostic_falls_back_to_cpu(monkeypatch):
    remover, torch = configured_remover(monkeypatch)
    calls = []
    message = (
        "The operator 'aten::upsample_bicubic2d.out' is not currently "
        "implemented for the MPS device. If you want this op to be "
        "considered for addition please comment on "
        "https://github.com/pytorch/pytorch/issues/141287 and mention "
        "use-case, that resulted in missing op as well as commit hash "
        "0123456789abcdef0123456789abcdef01234567. As a temporary fix, "
        "you can set the environment variable "
        "`PYTORCH_ENABLE_MPS_FALLBACK=1` to use the CPU as a fallback "
        "for this op. WARNING: this will be slower than running "
        "natively on MPS."
    )

    def infer(image, size, device):
        calls.append((size, device))
        if device == "mps":
            raise RuntimeError(message)
        return image

    monkeypatch.setattr(remover, "_infer", infer)
    image = Image.new("RGB", (8, 8))

    assert remover.remove(image) is image
    assert calls == [(1024, "mps"), (1024, "cpu")]
    assert remover._mps_disabled is True
    assert torch.mps.cache_clears == 1


def test_unrelated_not_implemented_error_propagates(monkeypatch):
    remover, _ = configured_remover(monkeypatch)
    calls = []

    def infer(image, size, device):
        calls.append(device)
        if device == "mps":
            raise NotImplementedError("kernel unavailable")
        return image

    monkeypatch.setattr(remover, "_infer", infer)
    image = Image.new("RGB", (8, 8))

    with pytest.raises(NotImplementedError, match="kernel unavailable"):
        remover.remove(image)
    assert calls == ["mps"]


def test_unrelated_runtime_error_propagates(monkeypatch):
    remover, _ = configured_remover(monkeypatch)

    def infer(image, size, device):
        raise RuntimeError("model is corrupt")

    monkeypatch.setattr(remover, "_infer", infer)

    with pytest.raises(RuntimeError, match="model is corrupt"):
        remover.remove(Image.new("RGB", (8, 8)))


def test_mps_memory_error_retries_smaller_size(monkeypatch):
    remover, torch = configured_remover(monkeypatch)
    remover._mps_size = 1536
    calls = []

    def infer(image, size, device):
        calls.append((size, device))
        if size == 1536:
            raise RuntimeError("MPS out of memory")
        return image

    monkeypatch.setattr(remover, "_infer", infer)
    image = Image.new("RGB", (8, 8))

    assert remover.remove(image) is image
    assert calls == [(1536, "mps"), (1024, "mps")]
    assert remover._mps_size == 1024
    assert remover._mps_disabled is False
    assert torch.mps.cache_clears == 1


def test_disabled_mps_is_skipped_on_subsequent_request(monkeypatch):
    remover, _ = configured_remover(monkeypatch)
    calls = []

    def infer(image, size, device):
        calls.append(device)
        if device == "mps":
            raise RuntimeError("The operator 'aten::foo' is not implemented for the MPS device.")
        return image

    monkeypatch.setattr(remover, "_infer", infer)
    image = Image.new("RGB", (8, 8))

    remover.remove(image)
    remover.remove(image)

    assert calls == ["mps", "cpu", "cpu"]


@pytest.mark.parametrize("message", [
    "The operator 'torchvision::deform_conv2d' is not implemented for the MPS device.",
    "The operator 'torchvision::deform_conv2d' is not currently implemented for the MPS device. "
    "If you want this op to be added in priority during the prototype phase of this feature, "
    "please comment on https://github.com/pytorch/pytorch/issues/77764. As a temporary fix, "
    "you can set the environment variable `PYTORCH_ENABLE_MPS_FALLBACK=1` to use the CPU as a fallback for this op.",
    "Could not run 'torchvision::deform_conv2d' with arguments from the 'MPS' backend.",
])
def test_reported_unsupported_messages_disable_mps(monkeypatch, message):
    remover, _ = configured_remover(monkeypatch)
    calls = []

    def infer(image, size, device):
        calls.append((size, device))
        if device == "mps":
            raise RuntimeError(message)
        return image

    monkeypatch.setattr(remover, "_infer", infer)
    image = Image.new("RGB", (8, 8))
    assert remover.remove(image) is image
    assert calls == [(1024, "mps"), (1024, "cpu")]
    assert remover._mps_disabled is True


def test_default_mps_memory_retries_reachable_lower_sizes(monkeypatch):
    remover, _ = configured_remover(monkeypatch)
    calls = []

    def infer(image, size, device):
        calls.append((size, device))
        if device == "mps" and size > 512:
            raise RuntimeError("MPS backend out of memory")
        return image

    monkeypatch.setattr(remover, "_infer", infer)
    image = Image.new("RGB", (8, 8))
    assert remover.remove(image) is image
    assert calls == [(1024, "mps"), (768, "mps"), (512, "mps")]
    assert remover._mps_size == 512
    assert remover._mps_disabled is False


def test_exhausted_mps_memory_uses_cpu_without_permanently_disabling_mps(monkeypatch):
    remover, _ = configured_remover(monkeypatch)
    calls = []

    def infer(image, size, device):
        calls.append((size, device))
        if device == "mps":
            raise RuntimeError("MPS backend out of memory")
        return image

    monkeypatch.setattr(remover, "_infer", infer)
    image = Image.new("RGB", (8, 8))
    assert remover.remove(image) is image
    assert remover.remove(image) is image
    assert calls == [
        (1024, "mps"), (768, "mps"), (512, "mps"), (1024, "cpu"),
        (512, "mps"), (1024, "cpu"),
    ]
    assert remover._mps_disabled is False


@pytest.mark.parametrize("message", ["allocation failed", "CPU out of memory"])
def test_unrelated_memory_like_runtime_errors_propagate(monkeypatch, message):
    remover, _ = configured_remover(monkeypatch)

    def infer(*args):
        raise RuntimeError(message)

    monkeypatch.setattr(remover, "_infer", infer)
    with pytest.raises(RuntimeError, match=message):
        remover.remove(Image.new("RGB", (8, 8)))


def test_quoted_mps_backend_dispatch_error_falls_back_to_cpu(monkeypatch):
    remover, _ = configured_remover(monkeypatch)
    calls = []

    def infer(image, size, device):
        calls.append((size, device))
        if device == "mps":
            raise RuntimeError(
                "Could not run 'aten::foo' with arguments from the 'MPS' backend."
            )
        return image

    monkeypatch.setattr(remover, "_infer", infer)
    image = Image.new("RGB", (8, 8))
    assert remover.remove(image) is image
    assert calls == [(1024, "mps"), (1024, "cpu")]
    assert remover._mps_disabled is True


@pytest.mark.parametrize("message", [
    "Invalid buffer size: 4.00 GB",
    "MPS backend: Invalid buffer size: 4096 MiB",
    "MPS invalid buffer size: 512 bytes",
])
def test_numeric_unit_invalid_buffer_size_retries_smaller_size(monkeypatch, message):
    remover, _ = configured_remover(monkeypatch)
    calls = []

    def infer(image, size, device):
        calls.append((size, device))
        if device == "mps" and size == 1024:
            raise RuntimeError(message)
        return image

    monkeypatch.setattr(remover, "_infer", infer)
    image = Image.new("RGB", (8, 8))
    assert remover.remove(image) is image
    assert calls == [(1024, "mps"), (768, "mps")]


@pytest.mark.parametrize("message", [
    "wrapper: Invalid buffer size: 4.00 GB",
    "Invalid buffer size: malformed input",
    "Invalid buffer size: 4.00",
    "Invalid buffer size: 4.00 GB trailing text",
    "MPS invalid buffer size: malformed input",
    "MPS invalid buffer size for shape validation",
    "MPS backend: Invalid buffer size: [4, 4]",
])
def test_unrelated_or_malformed_invalid_buffer_size_text_propagates(monkeypatch, message):
    remover, _ = configured_remover(monkeypatch)

    def infer(*args):
        raise RuntimeError(message)

    monkeypatch.setattr(remover, "_infer", infer)
    with pytest.raises(RuntimeError, match="(?i)invalid buffer size"):
        remover.remove(Image.new("RGB", (8, 8)))


def test_overlapping_mps_memory_dispatch_error_retries_instead_of_disabling(monkeypatch):
    remover, _ = configured_remover(monkeypatch)
    calls = []

    def infer(image, size, device):
        calls.append((size, device))
        if device == "mps" and size == 1024:
            raise RuntimeError(
                "Could not run 'aten::foo' with arguments from the 'MPS' backend: "
                "MPS backend out of memory"
            )
        return image

    monkeypatch.setattr(remover, "_infer", infer)
    image = Image.new("RGB", (8, 8))
    assert remover.remove(image) is image
    assert calls == [(1024, "mps"), (768, "mps")]
    assert remover._mps_disabled is False


@pytest.mark.parametrize("message", [
    "Could not run operation on the MPS backend",
    "Could not run 'aten::foo' with arguments from the CUDA backend",
    "MPS backend internal assertion failed",
    "MPS shape dimension 4 is not supported",
    "MPS invalid stride 0 for dimension 2",
    "MPS validation failed for shape [1, 3, 0, 0]",
])
def test_unrelated_mps_backend_errors_propagate(monkeypatch, message):
    remover, _ = configured_remover(monkeypatch)
    monkeypatch.setattr(remover, "_infer", lambda *args: (_ for _ in ()).throw(RuntimeError(message)))
    with pytest.raises(RuntimeError, match=re.escape(message)):
        remover.remove(Image.new("RGB", (8, 8)))


@pytest.mark.parametrize("message", [
    "MPS allocator: Invalid buffer size: 4.00 GB",
    "MPS backend: Invalid buffer size: 4096 MiB",
])
def test_known_mps_allocator_invalid_buffer_forms_retry(monkeypatch, message):
    remover, _ = configured_remover(monkeypatch)
    calls = []

    def infer(image, size, device):
        calls.append((size, device))
        if size == 1024:
            raise RuntimeError(message)
        return image

    monkeypatch.setattr(remover, "_infer", infer)
    image = Image.new("RGB", (8, 8))
    assert remover.remove(image) is image
    assert calls == [(1024, "mps"), (768, "mps")]


@pytest.mark.parametrize("message", [
    "MPS validation failed: invalid buffer size: 4 GB",
    "MPS malformed tensor invalid buffer size: 512 bytes",
    "arbitrary MPS text invalid buffer size: 8 MiB",
])
def test_arbitrary_mps_numeric_unit_suffix_propagates(monkeypatch, message):
    remover, _ = configured_remover(monkeypatch)
    monkeypatch.setattr(
        remover,
        "_infer",
        lambda *args: (_ for _ in ()).throw(RuntimeError(message)),
    )
    with pytest.raises(RuntimeError, match=re.escape(message)):
        remover.remove(Image.new("RGB", (8, 8)))
