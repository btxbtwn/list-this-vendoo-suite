from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from vendoo_studio.config import MAX_PHOTO_COUNT
from vendoo_studio.models.schema import ListingSchema
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

LIST_SPECIFIC_KEYS = frozenset({
    "features",
    "accents",
    "style",
    "occasion",
    "tags",
    "materials",
})

PATH_SPECIFIC_KEYS = frozenset({"categoryPath"})

IMAGE_CONTAINER_KEYS = frozenset({
    "images",
    "photos",
    "imageUrls",
    "itemImages",
    "media",
    "imageList",
    "pictures",
    "pictureUrls",
    "attachments",
    "photoUrls",
})

IMAGE_URL_KEYS = frozenset({
    "url",
    "originalUrl",
    "original",
    "src",
    "imageUrl",
    "downloadUrl",
    "largeUrl",
    "fullUrl",
    "secureUrl",
    "thumbnailUrl",
    "mediumUrl",
    "processedUrl",
    "editedUrl",
    "cdnUrl",
    "signedUrl",
    "location",
    "href",
    "uri",
    "publicUrl",
    "fileUrl",
    "highResUrl",
    "fullSizeUrl",
    "srcset",
    "currentSrc",
})

IMAGE_HOST_HINTS = (
    "cloudinary",
    "cloudfront",
    "googleusercontent",
    "firebasestorage",
    "storage.googleapis",
    "imgix",
    "akamai",
    "fastly",
    "imagekit",
    "cloudflare",
)

HTTP_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
IMAGE_EXT_RE = re.compile(r"\.(?:jpe?g|png|webp|gif|heic|heif|bmp|avif)(?:$|\?)", re.I)


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


ROUTE_ITEM_IDS = frozenset({"new", "edit", "create"})
VENDOO_HOSTS = frozenset({"web.vendoo.co", "app.vendoo.co"})
ITEM_PATH_RE = re.compile(r"/item/([^/?#]+)", re.I)


def parse_vendoo_draft_ref(raw: str | None) -> dict[str, str]:
    """Accept a Vendoo item URL or bare item ID and return a durable binding."""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("Paste a Vendoo draft link or item ID.")

    item_id = ""
    preferred_url = ""
    looks_like_url = (
        "://" in text
        or text.lower().startswith("web.vendoo.")
        or text.lower().startswith("app.vendoo.")
        or "/item/" in text
    )
    if looks_like_url:
        candidate = text if "://" in text else f"https://{text.lstrip('/')}"
        try:
            parsed = urlparse(candidate)
        except Exception as exc:
            raise ValueError("That does not look like a Vendoo draft link.") from exc
        host = (parsed.hostname or "").lower()
        if host and host not in VENDOO_HOSTS:
            raise ValueError("Use a web.vendoo.co or app.vendoo.co draft link.")
        match = ITEM_PATH_RE.search(parsed.path or "")
        if not match:
            raise ValueError("Vendoo link must include /app/item/<id>.")
        item_id = match.group(1).strip()
        preferred_url = urlunparse((
            "https",
            host or "web.vendoo.co",
            parsed.path,
            "",
            "",
            "",
        ))
    else:
        item_id = text

    item_id = item_id.strip()
    if not item_id or item_id.lower() in ROUTE_ITEM_IDS:
        raise ValueError("Open a saved Vendoo draft first (not /item/new).")
    if not all(ch.isalnum() or ch in "-_" for ch in item_id):
        raise ValueError("That does not look like a Vendoo item ID.")

    url = preferred_url if preferred_url and ITEM_PATH_RE.search(urlparse(preferred_url).path or "") else (
        f"https://web.vendoo.co/app/item/{item_id}"
    )
    return {"vendooItemId": item_id, "vendooUrl": url}


def merge_notes(existing: str | None, updates: dict[str, Any]) -> str:
    data = parse_notes(existing)
    binding_keys = {"vendooItemId", "vendooUrl"}
    for key, value in updates.items():
        if value is None:
            continue
        if key in binding_keys and not str(value).strip() and data.get(key):
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
        "condition": ListingSchema.validate_condition(_vendoo_label(general.get("condition"))),
        "primaryColor": _vendoo_label(general.get("primaryColor") or general.get("color")),
        "secondaryColor": _vendoo_label(general.get("secondaryColor")),
        "category_path": _category_path(general.get("categoryV2") or general.get("category")),
        "size": size,
        "sizeType": size_type,
        "size_us": size,
        "sku": _text(general.get("sku")),
        "tags": _string_list(general.get("tags")),
        "labels": _labels_from_vendoo(merged, general),
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


def image_urls_from_vendoo(
    item: dict | None,
    form: dict | None,
    extra: list[str] | None = None,
) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def add(raw: Any, *, require_image_hint: bool) -> None:
        if len(urls) >= MAX_PHOTO_COUNT:
            return
        for url in _iter_http_urls(raw):
            if url in seen or url.startswith(("blob:", "data:")):
                continue
            if require_image_hint and not _looks_like_image_url(url):
                continue
            seen.add(url)
            urls.append(url)
            if len(urls) >= MAX_PHOTO_COUNT:
                return

    def walk(value: Any, require_image_hint: bool, depth: int = 0) -> None:
        if len(urls) >= MAX_PHOTO_COUNT or value is None or depth > 10:
            return
        if isinstance(value, str):
            add(value, require_image_hint=require_image_hint)
            return
        if isinstance(value, list):
            for nested in value:
                walk(nested, require_image_hint, depth + 1)
            return
        if not isinstance(value, dict):
            return
        for key, nested in value.items():
            key_name = str(key)
            hinted = require_image_hint
            if key_name in IMAGE_CONTAINER_KEYS or key_name in IMAGE_URL_KEYS:
                hinted = False
            walk(nested, hinted, depth + 1)

    walk(extra or [], False)
    walk(item, True)
    walk(form, True)
    return urls


async def download_vendoo_photos(urls: list[str]) -> list[dict[str, Any]]:
    from vendoo_studio.services.safe_fetch import (
        DOWNLOAD_TIMEOUT_SEC,
        MAX_DOWNLOAD_BYTES,
        MAX_REDIRECTS,
        UnsafeURLError,
        validate_fetch_url,
    )

    photos: list[dict[str, Any]] = []
    headers = {
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": "https://web.vendoo.co/",
        "User-Agent": "Mozilla/5.0",
    }
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=DOWNLOAD_TIMEOUT_SEC,
        headers=headers,
        trust_env=False,
    ) as client:
        for index, raw_url in enumerate(urls[:MAX_PHOTO_COUNT]):
            try:
                content, content_type, final_url = await _download_public_image(client, raw_url)
            except Exception as exc:
                log.warning("Vendoo photo download failed for %s: %s", raw_url, exc)
                continue
            filename = _filename_from_url(final_url, index)
            try:
                photos.append(process_bytes(content, filename, content_type))
            except Exception as exc:
                log.warning("Vendoo photo rejected for %s: %s", final_url, exc)
    return photos


async def _download_public_image(client: httpx.AsyncClient, url: str) -> tuple[bytes, str | None, str]:
    from vendoo_studio.services.safe_fetch import (
        MAX_DOWNLOAD_BYTES,
        MAX_REDIRECTS,
        UnsafeURLError,
        resolve_fetch_target,
    )

    current = str(url or "").strip()
    for _ in range(MAX_REDIRECTS + 1):
        current, addresses = resolve_fetch_target(current, allow_http=False)
        parsed = urlparse(current)
        host = str(parsed.hostname or "")
        host_header = f"[{host}]" if ":" in host else host
        if parsed.port is not None:
            host_header = f"{host_header}:{parsed.port}"

        response = None
        last_connect_error = None
        for address in addresses:
            pinned_host = f"[{address}]" if ":" in address else address
            if parsed.port is not None:
                pinned_host = f"{pinned_host}:{parsed.port}"
            pinned_url = urlunparse(parsed._replace(netloc=pinned_host))
            request = client.build_request(
                "GET",
                pinned_url,
                headers={"Host": host_header, "Connection": "close"},
                extensions={"sni_hostname": host},
            )
            try:
                response = await client.send(request, stream=True, follow_redirects=False)
                break
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last_connect_error = exc
        if response is None:
            if last_connect_error is not None:
                raise last_connect_error
            raise UnsafeURLError(f"Could not connect to {host}")

        try:
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise UnsafeURLError("Redirect was missing a Location header")
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
            if content_type and not content_type.startswith("image/") and content_type not in {
                "application/octet-stream",
                "binary/octet-stream",
            }:
                raise UnsafeURLError(f"URL did not return an image ({content_type})")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > MAX_DOWNLOAD_BYTES:
                    raise UnsafeURLError("Image exceeded the download size limit")
            return bytes(content), content_type, current
        finally:
            await response.aclose()
    raise UnsafeURLError("Too many redirects")


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


def _vendoo_label(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    if text.startswith("v_") and len(text) > 2:
        rest = text[2:].replace("_", " ").strip()
        if rest:
            return rest[:1].upper() + rest[1:]
    return text


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


def _labels_from_vendoo(merged: dict[str, Any], general: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        for item in _string_list(value):
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            labels.append(item)

    add(general.get("labels"))
    add(merged.get("labels"))
    add(merged.get("labelNames"))
    add(merged.get("label_names"))
    named = merged.get("labelDetails") or general.get("labelDetails")
    if isinstance(named, list):
        for item in named:
            if isinstance(item, dict):
                add(item.get("displayName") or item.get("name") or item.get("label") or item.get("id"))
            else:
                add(item)
    return labels


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
        if dest in PATH_SPECIFIC_KEYS:
            out[dest] = _category_path_list(value)
            continue
        if dest in LIST_SPECIFIC_KEYS:
            items = _string_list(value)
            if items:
                out[dest] = items
            continue
        copied = _as_scalar_field(value)
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
        if text:
            return text
        path = value.get("displayPath") or value.get("path")
        if isinstance(path, list):
            return [part for part in (_text(item) for item in path) if part]
        return None
    return _text(value)


def _as_scalar_field(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        parts = [part for part in (_as_scalar_field(item) for item in value) if part not in (None, "")]
        if not parts:
            return None
        if len(parts) == 1:
            return parts[0]
        return str(parts[-1])
    if isinstance(value, dict):
        text = _text(value)
        if text:
            return text
        path = value.get("displayPath") or value.get("path")
        if isinstance(path, list):
            return _as_scalar_field(path)
        return None
    return _text(value)


def _category_path_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [part for part in (_text(item) if not isinstance(item, str) else item.strip() for item in value) if part]
    if isinstance(value, str):
        return [part.strip() for part in value.split(">") if part.strip()]
    if isinstance(value, dict):
        path = value.get("displayPath") or value.get("path") or value.get("breadcrumb")
        if isinstance(path, list):
            return _category_path_list(path)
        text = _text(value)
        return [text] if text else []
    return []


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
            copied = _as_scalar_field(value)
            if copied is None:
                continue
            category[key] = copied if isinstance(copied, str) else str(copied)
    if category:
        specifics["category_specifics"] = category
    return specifics


def _iter_http_urls(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    text = value.strip().strip("'\"")
    if not text or text.startswith(("blob:", "data:")):
        return []
    if text.startswith("//"):
        text = "https:" + text
    found: list[str] = []
    if text.startswith(("http://", "https://")):
        found.append(text.split()[0].rstrip(".,;"))
    else:
        found.extend(match.rstrip(".,;") for match in HTTP_URL_RE.findall(value))
    return found


def _looks_like_image_url(url: str) -> bool:
    parsed = urlparse(url)
    if IMAGE_EXT_RE.search(parsed.path) or IMAGE_EXT_RE.search(url):
        return True
    host = parsed.netloc.lower()
    if any(hint in host for hint in IMAGE_HOST_HINTS):
        return True
    if "vendoo" in host and any(part in host for part in ("img", "image", "cdn", "media", "static", "storage")):
        return True
    return False


def _filename_from_url(url: str, index: int) -> str:
    path = urlparse(url).path
    name = path.rsplit("/", 1)[-1] if path else ""
    if "." in name:
        return name
    return f"vendoo-{index + 1}.jpg"
