import asyncio
import base64
from io import BytesIO

from PIL import Image

from vendoo_studio.providers.xiaomi_mimo import VISION_MAX_SIDE, _encode_image
from vendoo_studio.services.listing_generate import (
    analyze_photos_with_tag_retry,
    unreadable_tag_fields,
)


def _photo(tmp_path, size, name="photo.jpg", fmt="JPEG"):
    path = tmp_path / name
    Image.new("RGB", size, (200, 30, 30)).save(path, format=fmt)
    return str(path)


def _decoded_size(url: str) -> tuple[int, int]:
    data = base64.b64decode(url.split(",", 1)[1])
    with Image.open(BytesIO(data)) as img:
        return img.size


def test_large_photo_is_downscaled_without_touching_original(tmp_path):
    path = _photo(tmp_path, (4032, 3024))
    before = (tmp_path / "photo.jpg").read_bytes()

    url = _encode_image(path)

    assert url.startswith("data:image/jpeg;base64,")
    assert _decoded_size(url) == (VISION_MAX_SIDE, 1200)
    assert (tmp_path / "photo.jpg").read_bytes() == before


def test_small_photo_and_full_resolution_send_original_bytes(tmp_path):
    small = _photo(tmp_path, (800, 600), name="small.png", fmt="PNG")
    large = _photo(tmp_path, (4032, 3024), name="large.jpg")

    assert _encode_image(small).startswith("data:image/png;base64,")
    assert _decoded_size(_encode_image(small)) == (800, 600)
    assert _decoded_size(_encode_image(large, max_side=None)) == (4032, 3024)


def test_unreadable_image_falls_back_to_raw_bytes(tmp_path):
    path = tmp_path / "photo.heic"
    path.write_bytes(b"not-an-image")
    assert _encode_image(str(path)).endswith(base64.b64encode(b"not-an-image").decode())


def test_unreadable_tag_fields_ignores_plain_missing_brand():
    assert unreadable_tag_fields({"brand": {"value": ""}, "size": {"value": "M", "source": "tag"}}) == []
    assert unreadable_tag_fields({
        "brand": {"value": "Unknown"},
        "size": {"value": "", "source": "unreadable"},
        "uncertainties": [{"field": "material", "issue": "Care tag too small to read"}],
    }) == ["brand", "size", "material"]


class _Provider:
    def __init__(self, first, retry):
        self.results = [first, retry]
        self.calls = []

    async def analyze_photos(self, paths, **kwargs):
        self.calls.append(kwargs)
        return self.results[len(self.calls) - 1]


def test_retry_at_full_resolution_merges_resolved_tag_fields(tmp_path):
    path = _photo(tmp_path, (4032, 3024))
    first = {"evidence": {
        "brand": {"value": "Levi's"},
        "size": {"value": "", "source": "unreadable"},
        "color": {"value": "Blue"},
        "uncertainties": [{"field": "size", "issue": "Size tag unreadable"}],
    }}
    retry = {"evidence": {
        "brand": {"value": "Something else"},
        "size": {"value": "32x30", "source": "tag"},
    }}
    provider = _Provider(first, retry)

    result = asyncio.run(analyze_photos_with_tag_retry(provider, [path], notes="n"))

    assert provider.calls == [{"notes": "n"}, {"notes": "n", "max_side": None}]
    evidence = result["evidence"]
    assert evidence["size"] == {"value": "32x30", "source": "tag"}
    assert evidence["brand"] == {"value": "Levi's"}
    assert evidence["uncertainties"] == []


def test_no_retry_when_photos_were_not_downscaled(tmp_path):
    path = _photo(tmp_path, (1200, 900))
    first = {"evidence": {"size": {"value": "", "source": "unreadable"}}}
    provider = _Provider(first, None)

    assert asyncio.run(analyze_photos_with_tag_retry(provider, [path])) is first
    assert len(provider.calls) == 1
