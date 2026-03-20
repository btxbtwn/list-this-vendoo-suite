#!/usr/bin/env python3
"""
Fetch a Raghouse catalog snapshot with full-collection awareness.

This helper:
- fetches the published collection index from `/collections.json`
- pages through the public product feed from `/products.json`
- writes a normalized JSON snapshot suitable for reproducible sourcing runs

The goal is to keep the skill from accidentally sourcing only from a narrow slice
like `get-this-box` when the user asked about the broader Raghouse catalog.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://raghouse.com"
DEFAULT_LIMIT = 250
USER_AGENT = "raghouse-box-sourcing/1.0"


def fetch_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} fetching {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error fetching {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"Timed out fetching {url}") from exc

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Received non-JSON response from {url}") from exc


def page_url(path: str, *, limit: int, page: int) -> str:
    query = urlencode({"limit": limit, "page": page})
    return f"{BASE_URL}{path}?{query}"


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def normalize_variant(variant: dict[str, Any]) -> dict[str, Any]:
    return {
        "price": str(variant.get("price", "")),
        "available": bool(variant.get("available", False)),
    }


def normalize_product(product: dict[str, Any]) -> dict[str, Any]:
    variants = product.get("variants") or []
    normalized_variants = [normalize_variant(variant) for variant in variants if isinstance(variant, dict)]

    return {
        "title": clean_text(product.get("title")),
        "handle": clean_text(product.get("handle")),
        "product_type": clean_text(product.get("product_type")),
        "tags": [clean_text(tag) for tag in product.get("tags") or [] if clean_text(tag)],
        "body_html": product.get("body_html") or "",
        "published_at": product.get("published_at"),
        "variants": normalized_variants,
    }


def normalize_collection(collection: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": clean_text(collection.get("title")),
        "handle": clean_text(collection.get("handle")),
        "products_count": int(collection.get("products_count") or 0),
        "published_at": collection.get("published_at"),
        "updated_at": collection.get("updated_at"),
    }


def fetch_all_collections(limit: int) -> list[dict[str, Any]]:
    all_collections: list[dict[str, Any]] = []
    page = 1
    while True:
        payload = fetch_json(page_url("/collections.json", limit=limit, page=page))
        collections = payload.get("collections") or []
        if not collections:
            break
        all_collections.extend(normalize_collection(item) for item in collections if isinstance(item, dict))
        if len(collections) < limit:
            break
        page += 1
    return all_collections


def fetch_all_products(limit: int, max_pages: int | None) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    seen_handles: set[str] = set()
    page = 1

    while True:
        if max_pages is not None and page > max_pages:
            break

        payload = fetch_json(page_url("/products.json", limit=limit, page=page))
        page_products = payload.get("products") or []
        if not page_products:
            break

        for item in page_products:
            if not isinstance(item, dict):
                continue
            normalized = normalize_product(item)
            handle = normalized["handle"]
            if not handle or handle in seen_handles:
                continue
            seen_handles.add(handle)
            products.append(normalized)

        if len(page_products) < limit:
            break
        page += 1

    return products


def build_snapshot(limit: int, max_pages: int | None) -> dict[str, Any]:
    collections = fetch_all_collections(limit)
    products = fetch_all_products(limit, max_pages)

    return {
        "captured_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": "Live Raghouse catalog via collections.json + products.json",
        "catalog_scope": (
            "Full public product feed plus published collection index. "
            "Recommendations should be allowed to come from any visible Raghouse collection, "
            "not only get-this-box."
        ),
        "collection_index_url": f"{BASE_URL}/collections.json?limit={limit}",
        "products_feed_url": f"{BASE_URL}/products.json?limit={limit}&page=N",
        "collections": collections,
        "products": products,
        "coverage": {
            "collection_count": len(collections),
            "product_count": len(products),
            "notes": [
                "Use collection discovery to understand scope, but rank boxes from the full product feed.",
                "If a local snapshot is heavily skewed toward `gtb` or `VIP_Product`, treat it as partial coverage rather than whole-site coverage.",
            ],
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch a full-scope Raghouse catalog snapshot.")
    parser.add_argument("--output", required=True, help="Path to write the snapshot JSON")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Page size for Shopify JSON endpoints")
    parser.add_argument("--max-pages", type=int, default=None, help="Optional cap on products.json pages")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    snapshot = build_snapshot(limit=args.limit, max_pages=args.max_pages)
    output_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote Raghouse catalog snapshot to {output_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
