from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from vendoo_studio.config import MAX_PHOTO_COUNT
from vendoo_studio.models.mercari_shipping import DEFAULT_SHIPPING_LABEL
from vendoo_studio.models.schema import DEPOP_OPTION_CODES, ListingSchema
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


def split_vendoo_labels(raw: str | None) -> list[str]:
    """Vendoo labels are stored on the conversation as one comma-separated string."""
    return [label.strip() for label in str(raw or "").split(",") if label.strip()]


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


# Vendoo does not store photo URLs: an item's images are records that name a
# path on its image server, which its own web app turns into a URL this way.
VENDOO_IMAGE_HOST = "https://images.vendoo.co"


def vendoo_image_url(record: Any) -> str:
    """The full-size URL for an image Vendoo hosts, or "" for any other record.

    Records that carry their own links — a marketplace import, a legacy upload —
    are left to the URL walk below, which knows to prefer an original over a
    thumbnail.
    """
    if not isinstance(record, dict):
        return ""
    url = str(record.get("url") or "").strip()
    image_id = str(record.get("id") or "").strip()
    # Images from before Vendoo's own image server still carry their URL.
    if url and "cloudinary" in url and image_id:
        return url
    if image_id and record.get("version") in (2, 3, "2", "3"):
        return f"{VENDOO_IMAGE_HOST}/{image_id.replace(chr(92), '/')}"
    return ""


def vendoo_image_records(item: dict | None, form: dict | None) -> list[Any]:
    """The item's photo records, in the order Vendoo keeps them."""
    merged = _merge_payloads(form, item)
    general = merged.get("generalDetails") if isinstance(merged.get("generalDetails"), dict) else {}
    for source in (general.get("images"), merged.get("images")):
        if isinstance(source, list) and source:
            return source
    return []


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
    # The item's own image records first, so its photos keep Vendoo's order.
    for record in vendoo_image_records(item, form):
        add(vendoo_image_url(record), require_image_hint=False)
    walk(item, True)
    walk(form, True)
    return urls


async def import_vendoo_draft(
    db: Any,
    conv_id: str,
    item: dict | None,
    form: dict | None,
    image_urls: list[str] | None = None,
    *,
    job: Any | None = None,
) -> dict[str, Any]:
    """Save a Vendoo draft as the listing's current revision and pull its photos."""
    from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
    from vendoo_studio.services.vendoo_create import resolve_label_display_names

    conv_repo = ConversationRepo(db)
    listing_repo = ListingRepo(db)
    listing = listing_from_vendoo(item, form)
    if job is not None and listing.get("labels"):
        listing["labels"] = await resolve_label_display_names(job, listing["labels"])
    current = listing_repo.get_current(conv_id)
    revision = listing_repo.save_revision(
        conv_id=conv_id,
        listing_json=listing,
        source="vendoo_import",
        parent_revision_id=current.current_revision_id if current else None,
    )

    conv = conv_repo.get(conv_id)
    if conv and listing.get("labels"):
        # Item Details reads labels from notes; keep names there when empty.
        if not str(parse_notes(conv.notes).get("vendooLabels") or "").strip():
            conv.notes = merge_notes(conv.notes, {
                "vendooLabels": ", ".join(str(label) for label in listing["labels"] if str(label).strip()),
            })
            db.commit()

    photo_warnings: list[str] = []
    existing_photos = conv_repo.get_photos(conv_id)
    if existing_photos:
        photo_count = len(existing_photos)
    else:
        urls = image_urls_from_vendoo(item, form, image_urls)
        imported = await download_vendoo_photos(urls)
        for meta in imported:
            conv_repo.add_photo(
                conv_id=conv_id,
                original_filename=meta["original_filename"],
                stored_filename=meta["stored_filename"],
                mime_type=meta["mime_type"],
                size_bytes=meta["size_bytes"],
                checksum=meta.get("checksum"),
                width=meta.get("width"),
                height=meta.get("height"),
            )
        photo_count = len(imported)
        if urls and photo_count < len(urls):
            photo_warnings.append(
                f"Imported {photo_count} of {len(urls)} photos. Add missing photos before sending if needed."
            )
        elif not urls:
            photo_warnings.append("No photos were found on the Vendoo listing.")

    return {
        "listing": listing,
        "revision": revision,
        "photo_count": photo_count,
        "photo_warnings": photo_warnings,
    }


# Marketplaces Vendoo retired: it keeps whatever listings an item still has on
# them, but leaves them out of the count that makes an item Active, so an item
# live on one of these alone is a draft.
VENDOO_UNLISTABLE_MARKETPLACES = frozenset({"sellhound", "kidizen", "tradesy"})


def _listing_entries(merged: dict[str, Any], *, external: bool = True) -> list[tuple[str, dict]]:
    """The item's marketplace listings, Vendoo's ``validate`` pseudo-entry aside.

    Vendoo keeps listings it posted under ``listings`` and ones the seller
    recorded elsewhere under ``externalListings``; its own selectors read both
    when deciding whether an item sold.
    """
    entries: list[tuple[str, dict]] = []
    keys = ["listings", "externalListings"] if external else ["listings"]
    for key in keys:
        group = merged.get(key) if isinstance(merged.get(key), dict) else {}
        for name, listing in group.items():
            if name == "validate" or not isinstance(listing, dict):
                continue
            entries.append((name, listing))
    return entries


def vendoo_item_sold(item: dict | None, form: dict | None = None) -> bool:
    """True when Vendoo counts the item as sold.

    Vendoo's Inventory tab does not read a single flag: an item is sold when it
    carries a sale record, when any listing carries sales, or when a listing --
    posted by Vendoo or recorded externally -- is flagged sold or shipped. A
    sale that Vendoo delisted afterwards keeps only the sale record, which is
    why the listing flags alone read as a draft.
    """
    merged = _merge_payloads(form, item)
    sale_record = merged.get("saleRecord")
    if isinstance(sale_record, dict) and sale_record:
        return True
    for _name, listing in _listing_entries(merged):
        status = listing.get("status") if isinstance(listing.get("status"), dict) else {}
        if status.get("sold") is True or status.get("shipped") is True:
            return True
        sales = listing.get("sales")
        if isinstance(sales, list) and any(sale for sale in sales):
            return True
    return False


def vendoo_item_status(item: dict | None, form: dict | None = None) -> str:
    """Vendoo's own inventory label for an item: ``draft``, ``active`` or ``sold``.

    Vendoo derives the Inventory tabs from the item's sale history and each
    marketplace listing's status flags, so the label follows the item rather
    than anything Studio did. Sold wins over listed, as Vendoo shows an item
    that sold on one marketplace while live on another under both tabs.
    """
    merged = _merge_payloads(form, item)
    if vendoo_item_sold(item, form):
        return "sold"
    for name, listing in _listing_entries(merged, external=False):
        if name in VENDOO_UNLISTABLE_MARKETPLACES:
            continue
        status = listing.get("status") if isinstance(listing.get("status"), dict) else {}
        if status.get("listed") is True:
            return "active"
    return "draft"


# Vendoo keys Vestiaire's API integration separately; Studio treats it as one marketplace.
VENDOO_MARKETPLACE_ALIASES = {"vestiaireApi": "vestiaire"}


def vendoo_listed_marketplaces(item: dict | None, form: dict | None = None) -> list[str]:
    """Marketplaces the item is live on, by Vendoo's own listing flags.

    Sold counts as listed: Vendoo keeps a sold listing on the marketplace it
    sold from, and the Inventory filters still match it there. An item Vendoo
    delisted after the sale keeps only its sale record, so that record's
    marketplace stands in for the listing flag it cleared.
    """
    merged = _merge_payloads(form, item)
    live: set[str] = set()
    for name, listing in _listing_entries(merged, external=False):
        status = listing.get("status") if isinstance(listing.get("status"), dict) else {}
        if status.get("listed") is True or status.get("sold") is True or status.get("shipped") is True:
            live.add(VENDOO_MARKETPLACE_ALIASES.get(name, name))
    sale_record = merged.get("saleRecord") if isinstance(merged.get("saleRecord"), dict) else {}
    sold_on = str(sale_record.get("marketplace") or "").strip()
    if sold_on:
        live.add(VENDOO_MARKETPLACE_ALIASES.get(sold_on, sold_on))
    return sorted(live)


def _as_iso(raw: Any) -> str:
    """One Vendoo date as an ISO 8601 string, whatever shape it arrived in.

    ``/api/item`` answers Firestore timestamps as ``{_seconds, _nanoseconds}``,
    a document read straight from Firestore carries an ISO string, and a few
    fields arrive as epoch numbers.
    """
    from datetime import UTC, datetime

    if isinstance(raw, dict):
        seconds = raw.get("_seconds", raw.get("seconds"))
        if seconds is None:
            return ""
        raw = float(seconds)
    if isinstance(raw, (int, float)):
        # Vendoo writes seconds in timestamps and milliseconds in plain numbers;
        # anything past the year 3000 read as seconds is really milliseconds.
        seconds = float(raw) / 1000 if float(raw) > 32503680000 else float(raw)
        try:
            return datetime.fromtimestamp(seconds, UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).isoformat()


def _newest(*values: Any) -> str:
    """The latest of these Vendoo dates, as an ISO string."""
    stamps = []
    for value in values:
        if isinstance(value, list):
            stamps.extend(_as_iso(entry) for entry in value)
        else:
            stamps.append(_as_iso(value))
    return max((stamp for stamp in stamps if stamp), default="")


def _listing_status_date(listing: dict, key: str) -> Any:
    status_dates = listing.get("lastStatusDate")
    return status_dates.get(key) if isinstance(status_dates, dict) else None


def _listing_listed_at(listing: dict) -> str:
    """When this marketplace listing last went live.

    Vendoo's own selector takes the newest of the listing's relist history and
    its last "listed" status stamp, so a relisted item reads as fresh.
    """
    return _newest(
        listing.get("dateListed"),
        listing.get("lastDateListed"),
        _listing_status_date(listing, "listed"),
    )


def vendoo_dates(item: dict | None, form: dict | None = None) -> dict[str, Any]:
    """Every time-tracking stamp Vendoo carries for an item, as ISO strings.

    Vendoo keeps the item's own ``dateCreated``/``dateLastModified`` and then a
    second set per marketplace listing: when it went live (and every relist
    since), when it sold, and when it was last touched. Studio keeps the lot, so
    a listing's whole history is answerable without going back to Vendoo.
    """
    merged = _merge_payloads(form, item)
    sale_record = merged.get("saleRecord") if isinstance(merged.get("saleRecord"), dict) else {}
    listed_by_marketplace: dict[str, str] = {}
    sold_by_marketplace: dict[str, str] = {}
    for name, listing in _listing_entries(merged):
        market = VENDOO_MARKETPLACE_ALIASES.get(name, name)
        listed = _listing_listed_at(listing)
        if listed:
            listed_by_marketplace[market] = listed
        sold = _newest(listing.get("dateSold"), _listing_status_date(listing, "sold"))
        if sold:
            sold_by_marketplace[market] = sold
    created = _as_iso(merged.get("dateCreated") or merged.get("createdAt"))
    listed = _newest(*listed_by_marketplace.values(), sale_record.get("date_listed"))
    return {
        "created": created,
        # An item Vendoo has never edited still carries its creation date.
        "modified": _newest(
            merged.get("dateLastModified"),
            merged.get("updatedAt"),
            merged.get("savedAt"),
        )
        or created,
        # A listing that has never gone live falls back to its creation date, the
        # way Vendoo's own "Listing Date" column does.
        "listed": listed or created,
        "sold": _newest(*sold_by_marketplace.values(), sale_record.get("date_sold"), merged.get("dateSold")),
        "listedByMarketplace": listed_by_marketplace,
        "soldByMarketplace": sold_by_marketplace,
    }


def vendoo_listed_at(item: dict | None, form: dict | None = None) -> str:
    """When the item last went live -- what says how stale a listing has gone."""
    return str(vendoo_dates(item, form).get("listed") or "")


def vendoo_updated_at(item: dict | None, form: dict | None = None) -> str:
    """The item's last Vendoo write, as a comparable string.

    Vendoo stamps items with ``dateLastModified``; ``/api/item`` answers
    Firestore timestamps as ``{_seconds, _nanoseconds}`` where a document read
    straight from Firestore carries an ISO string.
    """
    merged = _merge_payloads(form, item)
    raw = (
        merged.get("dateLastModified")
        or merged.get("updatedAt")
        or merged.get("savedAt")
        or merged.get("createdAt")
    )
    if isinstance(raw, dict):
        seconds = raw.get("_seconds") or raw.get("seconds")
        nanos = raw.get("_nanoseconds") or raw.get("nanoseconds") or 0
        return f"{seconds}.{nanos}" if seconds is not None else ""
    return str(raw or "").strip()


async def import_vendoo_item(
    db: Any,
    *,
    item_id: str,
    item: dict | None = None,
    form: dict | None = None,
    url: str | None = None,
    source: str | None = None,
    image_urls: list[str] | None = None,
) -> dict[str, Any]:
    """Bind one Vendoo item to a Studio listing, with its fields and its photos.

    Re-importing the same item reuses its conversation, so a bulk run is safe to
    repeat.
    """
    from vendoo_studio.repositories.queries import ConversationRepo, JobRepo

    listing = listing_from_vendoo(item, form)
    status = vendoo_item_status(item, form)
    marketplaces = vendoo_listed_marketplaces(item, form)
    item_url = (url or "").strip() or f"https://web.vendoo.co/app/item/{item_id}"
    urls = image_urls_from_vendoo(item, form, image_urls)

    conv_repo = ConversationRepo(db)
    conv = conv_repo.find_by_vendoo_item_id(item_id)
    reused = conv is not None
    if conv is None:
        conv = conv_repo.create(title=listing.get("title") or "Imported from Vendoo")

    conv.notes = merge_notes(conv.notes, {
        "vendooItemId": item_id,
        "vendooUrl": item_url,
        "vendooStatus": status,
        "vendooMarketplaces": marketplaces,
        "vendooDates": vendoo_dates(item, form),
        # Vendoo's own image stands in for the sidebar thumbnail when a photo
        # download did not make it.
        "vendooCoverUrl": urls[0] if urls else "",
    })
    db.commit()
    db.refresh(conv)

    result = await import_vendoo_draft(db, conv.id, item, form, image_urls)
    conv_repo.add_message(
        conv.id,
        "system",
        f"{'Re-imported' if reused else 'Imported'} from Vendoo item {item_id}.",
    )

    job_repo = JobRepo(db)
    job = job_repo.create(
        conv_id=conv.id,
        approved_revision_id=result["revision"].id,
        listing_snapshot=result["listing"],
        vendoo_item_id=item_id,
        vendoo_url=item_url,
        status="imported",
        current_step="imported",
    )
    job_repo.add_event(job.id, "imported", "imported")
    # Resolve opaque label ids now that a job can reach the seller's catalog.
    listing = result["listing"]
    if listing.get("labels"):
        from vendoo_studio.services.vendoo_create import resolve_label_display_names
        from vendoo_studio.repositories.queries import ListingRepo

        named = await resolve_label_display_names(job, listing["labels"])
        if named != list(listing["labels"]):
            listing = {**listing, "labels": named}
            ListingRepo(db).save_revision(
                conv.id,
                listing,
                source="vendoo_import",
                parent_revision_id=result["revision"].id,
            )
            job.listing_snapshot = listing
            result["listing"] = listing
            conv.notes = merge_notes(conv.notes, {"vendooLabels": ", ".join(named)})
            db.commit()
            db.refresh(conv)
            db.refresh(job)
    job_repo.save_vendoo_draft(
        job.id,
        item=item,
        form=form,
        item_id=item_id,
        url=item_url,
        source=(source or "import"),
        step="imported",
    )
    conv_repo.update_status(conv.id, status)

    # Last: an item is only "seen at this stamp" once its photos and job are
    # stored, so a run cut short part-way through one is redone, not skipped.
    conv.notes = merge_notes(conv.notes, {"vendooUpdatedAt": vendoo_updated_at(item, form)})
    db.commit()

    return {
        "conversation": conv,
        "job": job,
        "listing": result["listing"],
        "status": status,
        "reused": reused,
        "photo_count": result["photo_count"],
        "photo_warnings": result["photo_warnings"],
    }


async def attach_vendoo_photos(db: Any, conv_id: str, item: dict | None, form: dict | None = None) -> int:
    """Fetch an item's photos for a listing that has none.

    A listing whose fields arrived without its photos — an import that ran
    before the image records could be resolved, a spell of failed downloads —
    is repaired by fetching the photos alone, rather than by importing the whole
    item again over the top of it.
    """
    from vendoo_studio.repositories.queries import ConversationRepo

    conv_repo = ConversationRepo(db)
    if conv_repo.get_photos(conv_id):
        return 0
    urls = image_urls_from_vendoo(item, form)
    if not urls:
        return 0

    imported = await download_vendoo_photos(urls)
    for meta in imported:
        conv_repo.add_photo(
            conv_id=conv_id,
            original_filename=meta["original_filename"],
            stored_filename=meta["stored_filename"],
            mime_type=meta["mime_type"],
            size_bytes=meta["size_bytes"],
            checksum=meta.get("checksum"),
            width=meta.get("width"),
            height=meta.get("height"),
        )
    conv = conv_repo.get(conv_id)
    if conv is not None and urls:
        conv.notes = merge_notes(conv.notes, {"vendooCoverUrl": urls[0]})
    db.commit()
    return len(imported)


# A listing's photos come down together: a whole-inventory import is thousands
# of images, and one at a time would take hours of waiting on the network.
PHOTO_DOWNLOAD_CONCURRENCY = 6


async def download_vendoo_photos(urls: list[str]) -> list[dict[str, Any]]:
    from vendoo_studio.services.safe_fetch import (
        DOWNLOAD_TIMEOUT_SEC,
    )

    headers = {
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": "https://web.vendoo.co/",
        "User-Agent": "Mozilla/5.0",
    }
    wanted = urls[:MAX_PHOTO_COUNT]
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=DOWNLOAD_TIMEOUT_SEC,
        headers=headers,
        trust_env=False,
    ) as client:
        limit = asyncio.Semaphore(PHOTO_DOWNLOAD_CONCURRENCY)

        async def fetch(index: int, raw_url: str) -> dict[str, Any] | None:
            async with limit:
                try:
                    content, content_type, final_url = await _download_public_image(client, raw_url)
                except Exception as exc:
                    log.warning("Vendoo photo download failed for %s: %s", raw_url, exc)
                    return None
            filename = _filename_from_url(final_url, index)
            try:
                # Writing and decoding the file is blocking work; keep it off the loop.
                return await asyncio.to_thread(process_bytes, content, filename, content_type)
            except Exception as exc:
                log.warning("Vendoo photo rejected for %s: %s", final_url, exc)
                return None

        results = await asyncio.gather(*(fetch(i, url) for i, url in enumerate(wanted)))
    # Keep Vendoo's order: it is the listing's photo order.
    return [photo for photo in results if photo]


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
    """Vendoo inventory labels as display names when the payload has them.

    An item's ``labels`` array is ids into the seller's label catalog. Prefer
    ``labelDetails`` / ``labelNames`` so Item Details shows "Women" instead of
    ``g8MHWF7K…``. Ids that never resolve stay as-is for a later catalog lookup.
    """
    labels: list[str] = []
    seen: set[str] = set()
    id_to_name: dict[str, str] = {}

    def remember_named(value: Any) -> None:
        if not isinstance(value, list):
            return
        for item in value:
            if isinstance(item, dict):
                label_id = _text(item.get("id"))
                name = _text(
                    item.get("displayName") or item.get("name") or item.get("label")
                )
                if label_id and name:
                    id_to_name[label_id] = name
            else:
                text = _text(item)
                if text:
                    id_to_name.setdefault(text, text)

    remember_named(merged.get("labelDetails") or general.get("labelDetails"))

    def add(value: Any) -> None:
        for item in _string_list(value):
            display = id_to_name.get(item, item)
            key = display.lower()
            if key in seen:
                continue
            seen.add(key)
            labels.append(display)

    add(merged.get("labelNames"))
    add(merged.get("label_names"))
    add(general.get("labelNames"))
    for item in id_to_name.values():
        add(item)
    add(general.get("labels"))
    add(merged.get("labels"))
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
        return ", ".join(str(part) for part in parts)
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
    label = _text(specifics.get("shippingLabel")) or DEFAULT_SHIPPING_LABEL
    specifics["shippingLabel"] = label
    return specifics


def _depop_specifics(section: Any) -> dict[str, Any]:
    specifics = _copy_specifics(section)
    # Vendoo stores style/age/source as option codes; Studio speaks labels.
    for field, codes in DEPOP_OPTION_CODES.items():
        labels = {code: label for label, code in codes.items()}
        value = specifics.get(field)
        if isinstance(value, list):
            specifics[field] = [labels.get(item, item) for item in value]
        elif isinstance(value, str):
            specifics[field] = labels.get(value, value)
    return specifics


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
