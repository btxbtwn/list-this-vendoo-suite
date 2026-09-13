from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from vendoo_studio.config import MAX_PHOTO_COUNT
from vendoo_studio.services.photos import process_bytes

log = logging.getLogger("vendoo_studio.vendoo_import")

SKIP_SPECIFIC_KEYS = frozenset({
    "status",
    "listed",
    "id",
    "itemId",
    "itemID",
    "createdAt",
    "updatedAt",
    "errors",
    "warnings",
    "images",
    "photos",
})

ETSY_KEY_MAP = {
    "whoMade": "who_made",
    "whatIs": "what_is",
    "whenMade": "when_made",
}

IMAGE_URL_KEYS = (
    "url",
    "originalUrl",
    "original",
    "src",
    "imageUrl",
    "downloadUrl",
    "largeUrl",
    "fullUrl",
    "secureUrl",
)


def parse_notes(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def vendoo_binding(notes: str | None) -> dict[str, str]:
    data = parse_notes(notes)
    item_id = str(data.get("vendooItemId") or "").strip()
    url = str(data.get("vendooUrl") or "").strip()
    out: dict[str, str] = {}
    if item_id:
        out["vendooItemId"] = item_id
    if url:
        out["vendooUrl"] = url
    elif item_id:
        out["vendooUrl"] = f"https://web.vendoo.co/app/item/{item_id}"
    return out


def merge_notes(existing: str | None, updates: dict[str, Any]) -> str:
    data = parse_notes(existing)
    for key, value in updates.items():
        if value is None:
            continue
        data[key] = value
    return json.dumps(data)


def listing_from_vendoo(item: dict | None, form: dict | None) -> dict[str, Any]:
    merged = _merge_payloads(form, item)
    general = merged.get("generalDetails") if isinstance(merged.get("generalDetails"), dict) else {}
    listings = merged.get("listings") if isinstance(merged.get("listings"), dict) else {}

    title = _text(general.get("title")) or "Imported from Vendoo"
    description = _text(general.get("description")) or title
    price = _number(general.get("price")) or 0
    cost = _number(general.get("cost"))
    quantity = _int(general.get("quantity"))
    if quantity is None:
        quantity = 1

    size_raw = general.get("size")
    size = _text(_nested_option(size_raw) or size_raw)
    size_type = _text(general.get("sizeType") or _nested_scale(size_raw))
    weight = general.get("weight") if isinstance(general.get("weight"), dict) else {}
    dims = general.get("dimensions") if isinstance(general.get("dimensions"), dict) else {}
    package = _package_dimensions(dims) or "13x10x3"

    listing: dict[str, Any] = {
        "title": title,
        "description": description,
        "price": price,
        "cost": cost,
        "quantity": quantity,
        "brand": _text(general.get("brand")),
        "condition": _text(general.get("condition")),
        "primaryColor": _text(general.get("primaryColor") or general.get("color")),
        "secondaryColor": _text(general.get("secondaryColor")),
        "category_path": _category_path(general.get("categoryV2") or general.get("category")),
        "size": size,
        "sizeType": size_type,
        "size_us": size,
        "sku": _text(general.get("sku")),
        "tags": _string_list(general.get("tags")),
        "labels": _string_list(general.get("labels")),
        "weight_lb": _int(weight.get("pounds")) or 0,
        "weight_oz": _int(weight.get("ounces")) if _int(weight.get("ounces")) is not None else 8,
        "package_dimensions_in": package,
        "internal_notes": _text(general.get("notes")),
        "ebay_specifics": _ebay_specifics(listings.get("ebay"), size, size_type),
        "poshmark_specifics": _poshmark_specifics(listings.get("poshmark")),
        "mercari_specifics": _mercari_specifics(listings.get("mercari")),
        "depop_specifics": _depop_specifics(listings.get("depop")),
        "etsy_specifics": _etsy_specifics(listings.get("etsy")),
    }
    return listing


def image_urls_from_vendoo(item: dict | None, form: dict | None) -> list[str]:
    blobs: list[Any] = [item, form]
    if isinstance(item, dict):
        blobs.append(item.get("generalDetails"))
    if isinstance(form, dict):
        blobs.append(form.get("generalDetails"))
    urls: list[str] = []
    seen: set[str] = set()
    for blob in blobs:
        if not isinstance(blob, dict):
            continue
        for key in ("images", "photos", "imageUrls"):
            for url in _collect_image_urls(blob.get(key)):
                if url in seen:
                    continue
                seen.add(url)
                urls.append(url)
                if len(urls) >= MAX_PHOTO_COUNT:
                    return urls
    return urls


async def download_vendoo_photos(urls: list[str]) -> list[dict[str, Any]]:
    photos: list[dict[str, Any]] = []
    if not urls:
        return photos
    async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
        for index, url in enumerate(urls[:MAX_PHOTO_COUNT]):
            try:
                response = await client.get(url)
                response.raise_for_status()
            except Exception as exc:
                log.warning("Vendoo photo download failed for %s: %s", url, exc)
                continue
            filename = _filename_from_url(url, index)
            try:
                photos.append(process_bytes(response.content, filename, response.headers.get("content-type")))
            except Exception as exc:
                log.warning("Vendoo photo rejected for %s: %s", url, exc)
    return photos


def _merge_payloads(form: dict | None, item: dict | None) -> dict[str, Any]:
    form_data = form if isinstance(form, dict) else {}
    item_data = item if isinstance(item, dict) else {}
    form_general = form_data.get("generalDetails") if isinstance(form_data.get("generalDetails"), dict) else {}
    item_general = item_data.get("generalDetails") if isinstance(item_data.get("generalDetails"), dict) else {}
    form_listings = form_data.get("listings") if isinstance(form_data.get("listings"), dict) else {}
    item_listings = item_data.get("listings") if isinstance(item_data.get("listings"), dict) else {}
    return {
        **form_data,
        **item_data,
        "generalDetails": {**form_general, **item_general},
        "listings": {**form_listings, **item_listings},
        "images": item_data.get("images") if item_data.get("images") is not None else form_data.get("images"),
    }


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("displayName", "label", "name", "value"):
            text = _text(value.get(key))
            if text:
                return text
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        return _number(value.get("value") or value.get("amount"))
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _number(value)
    if number is None:
        return None
    return int(number)


def _string_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            text = _text(item)
            if text:
                out.append(text)
        return out
    text = _text(value)
    return [text] if text else []


def _nested_option(value: Any) -> Any:
    if isinstance(value, dict):
        if "option" in value:
            return value.get("option")
        if isinstance(value.get("value"), dict):
            return value.get("value")
    return None


def _nested_scale(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("scale") or value.get("sizeType")
    return None


def _category_path(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list):
        parts = [_text(part) for part in value]
        joined = " > ".join(part for part in parts if part)
        return joined or None
    if isinstance(value, dict):
        path = value.get("displayPath") or value.get("path") or value.get("breadcrumb")
        if isinstance(path, list):
            return _category_path(path)
        for key in ("displayName", "name", "label", "value"):
            text = _text(value.get(key))
            if text:
                return text
    return None


def _package_dimensions(dims: dict[str, Any]) -> str | None:
    length = _text(dims.get("length"))
    width = _text(dims.get("width"))
    height = _text(dims.get("height"))
    if length and width and height:
        return f"{length}x{width}x{height}"
    return None


def _section_fields(section: Any) -> dict[str, Any]:
    if not isinstance(section, dict):
        return {}
    merged: dict[str, Any] = {}
    for key in ("overrides", "marketplaceSpecifics", "categorySpecifics"):
        nested = section.get(key)
        if isinstance(nested, dict):
            merged.update(nested)
    for key, value in section.items():
        if key in {"overrides", "marketplaceSpecifics", "categorySpecifics"}:
            continue
        if key in SKIP_SPECIFIC_KEYS:
            continue
        if key not in merged:
            merged[key] = value
    return merged


def _copy_specifics(section: Any, *, rename: dict[str, str] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in _section_fields(section).items():
        if key in SKIP_SPECIFIC_KEYS:
            continue
        dest = (rename or {}).get(key, key)
        copied = _copy_value(value)
        if copied is not None:
            out[dest] = copied
    return out


def _copy_value(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        items = [_copy_value(item) for item in value]
        cleaned = [item for item in items if item not in (None, "")]
        return cleaned or None
    if isinstance(value, dict):
        text = _text(value)
        path = value.get("displayPath") or value.get("path")
        if isinstance(path, list):
            return [part for part in (_text(item) for item in path) if part]
        return text
    return _text(value)


def _ebay_specifics(section: Any, size: str | None, size_type: str | None) -> dict[str, Any]:
    specifics = _copy_specifics(section)
    if size and not specifics.get("size"):
        specifics["size"] = size
    if size_type and not specifics.get("sizeType"):
        specifics["sizeType"] = size_type
    return specifics


def _poshmark_specifics(section: Any) -> dict[str, Any]:
    specifics = _copy_specifics(section)
    path = specifics.get("categoryPath")
    if isinstance(path, str):
        specifics["categoryPath"] = [part.strip() for part in path.split(">") if part.strip()]
    elif not isinstance(path, list):
        specifics["categoryPath"] = []
    price = _number(specifics.get("originalPrice"))
    specifics["originalPrice"] = price or 0
    return specifics


def _mercari_specifics(section: Any) -> dict[str, Any]:
    specifics = _copy_specifics(section)
    path = specifics.get("categoryPath")
    if isinstance(path, str):
        specifics["categoryPath"] = [part.strip() for part in path.split(">") if part.strip()]
    elif not isinstance(path, list):
        specifics["categoryPath"] = []
    label = _text(specifics.get("shippingLabel")) or "USPS Ground Advantage"
    specifics["shippingLabel"] = label
    return specifics


def _depop_specifics(section: Any) -> dict[str, Any]:
    return _copy_specifics(section)


def _etsy_specifics(section: Any) -> dict[str, Any]:
    specifics = _copy_specifics(section, rename=ETSY_KEY_MAP)
    category = {}
    if isinstance(section, dict) and isinstance(section.get("categorySpecifics"), dict):
        for key, value in section["categorySpecifics"].items():
            copied = _copy_value(value)
            if copied is not None:
                category[key] = copied if isinstance(copied, str) else str(copied)
    if category:
        specifics["category_specifics"] = category
    return specifics


def _collect_image_urls(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, str):
        if value.startswith("http://") or value.startswith("https://"):
            urls.append(value)
        return urls
    if isinstance(value, list):
        for item in value:
            urls.extend(_collect_image_urls(item))
        return urls
    if isinstance(value, dict):
        for key in IMAGE_URL_KEYS:
            if value.get(key):
                urls.extend(_collect_image_urls(value.get(key)))
                break
    return urls


def _filename_from_url(url: str, index: int) -> str:
    path = urlparse(url).path
    name = path.rsplit("/", 1)[-1] if path else ""
    if "." in name:
        return name
    return f"vendoo-{index + 1}.jpg"
