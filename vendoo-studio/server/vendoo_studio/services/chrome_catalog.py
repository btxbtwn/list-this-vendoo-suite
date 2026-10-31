"""Poshmark's and Depop's own categories and parcels, as Chrome reads them.

The extension is asked when Chrome is connected, because that is the catalog
and the parcel list a direct List actually uses. Without Chrome, the categories
come from the native form catalogs (see ``native_category_match``). Neither
path writes ``marketplace_category_ids``.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from types import SimpleNamespace
from typing import Any

log = logging.getLogger("vendoo_studio.chrome_catalog")

CHROME_MARKETS = ("poshmark", "depop")
# Depop's USPS parcel titles (the words the listing form stores).
KNOWN_PARCELS = frozenset({
    "extraextrasmall", "extrasmall", "small", "medium", "large", "extralarge",
})


def name_key(value: Any) -> str:
    """The same comparison the extension uses for Depop names and parcel titles."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text.lower().replace("&", "and"))


def parcel_key(value: Any) -> str:
    return name_key(value)


def apply_direct_ids(listing: dict, categories: dict | None) -> bool:
    """Remember Poshmark's and Depop's ids on the listing. Vendoo's ids stay as they are."""
    if not isinstance(listing, dict) or not isinstance(categories, dict):
        return False
    current = dict(listing.get("direct_category_ids")) if isinstance(listing.get("direct_category_ids"), dict) else {}
    changed = False
    for key in CHROME_MARKETS:
        value = str(categories.get(key) or "").strip()
        if value and current.get(key) != value:
            current[key] = value
            changed = True
    if changed:
        listing["direct_category_ids"] = current
    return changed


def keep_direct_categories(previous: dict, incoming: dict) -> None:
    """A save from the editor keeps a category Chrome already resolved."""
    if not isinstance(previous, dict) or not isinstance(incoming, dict):
        return
    old = previous.get("direct_category_ids") if isinstance(previous.get("direct_category_ids"), dict) else {}
    if not any(str(old.get(key) or "").strip() for key in CHROME_MARKETS):
        return
    if not isinstance(incoming.get("direct_category_ids"), dict):
        incoming["direct_category_ids"] = dict(old)
        return
    merged = dict(incoming["direct_category_ids"])
    for key in CHROME_MARKETS:
        if str(old.get(key) or "").strip() and not str(merged.get(key) or "").strip():
            merged[key] = old[key]
    incoming["direct_category_ids"] = merged


def remember_direct_categories(db, revision, categories: dict | None) -> None:
    """Write the resolved ids onto the current revision, without a new revision."""
    if revision is None or not isinstance(getattr(revision, "listing_json", None), dict) or not categories:
        return
    updated = dict(revision.listing_json)
    if not apply_direct_ids(updated, categories):
        return
    revision.listing_json = updated
    db.commit()


def apply_preview(found: list[dict], preview: dict | None, marketplace: str) -> list[dict]:
    """Add the size, category, and parcel refusals Chrome found. A live parcel match wins."""
    if not isinstance(preview, dict):
        return found
    gaps = preview.get("gaps") if isinstance(preview.get("gaps"), dict) else {}
    extra = []
    for item in gaps.get(marketplace) or []:
        if isinstance(item, dict) and str(item.get("field") or "") and str(item.get("message") or ""):
            extra.append({
                "field": str(item["field"]), "message": str(item["message"]), "blocking": bool(item.get("blocking", True)),
            })
    if marketplace == "depop" and preview.get("parcels_checked") and not any(
        item["field"] == "depop_specifics.parcelSize" and "does not offer" in item["message"] for item in extra
    ):
        found = [item for item in found if not (item["field"] == "depop_specifics.parcelSize" and "does not offer" in item["message"])]
    seen = {(item["field"], item["message"]) for item in found}
    for item in extra:
        key = (item["field"], item["message"])
        if key not in seen:
            found.append(item)
            seen.add(key)
    found.sort(key=lambda item: not item["blocking"])
    return found


def preview_categories(preview: dict | None) -> dict[str, str]:
    raw = preview.get("categories") if isinstance(preview, dict) and isinstance(preview.get("categories"), dict) else {}
    return {key: str(raw.get(key)).strip() for key in CHROME_MARKETS if str(raw.get(key) or "").strip()}


async def live_preview(listing: dict) -> dict | None:
    """Ask the connected extension. A stand-in connection answers nothing."""
    from vendoo_studio.services.extension_connection import extension_manager
    from vendoo_studio.services import browser_bridge

    if not getattr(extension_manager, "connected", False) or not hasattr(extension_manager, "register_wait"):
        return None
    try:
        result = await browser_bridge.request(
            SimpleNamespace(id=None), "marketplace.direct_check", {"listing": listing}, timeout=25,
        )
    except Exception as exc:  # noqa: BLE001 - List still checks inside Chrome when this read fails
        log.info("No direct catalog check: %s", exc)
        return None
    return result if isinstance(result, dict) and result.get("ok") else None
