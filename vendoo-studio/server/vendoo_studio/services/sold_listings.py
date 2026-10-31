"""Dated sold listings for sourcing prices, read from the marketplaces themselves.

eBay refuses anything that is not a browser, so its sold search is read through
the seller's own Chrome by the extension. Poshmark serves its search to a plain
request, with the time each listing sold. Mercari shows no sale date on a search
result, Depop has no sold filter and Etsy hides the price of a sold item, so
those three are not read here; the seller's own sales on them still count.

Nothing here estimates a price or judges a listing. It returns what a search
found; ``box_scout`` drops the ones that do not fit the theme and decides whether
enough are left.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.request
import uuid
from datetime import date
from urllib.parse import urlencode

log = logging.getLogger("vendoo_studio.sold_listings")

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
POSHMARK_SEARCH = "https://poshmark.com/search"
# The extension opens one search at a time in a background tab.
EBAY_SECONDS_PER_SEARCH = 20
EBAY_EXTENSION_VERSION = (0, 2, 35)  # the first extension that answers market.sold_listings
MAX_AGE_DAYS = 90
MONTHS = {name: number for number, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}

# A theme with no garment, or only "accessories", names nothing a search can compare.
UNSEARCHABLE_RE = re.compile(r"\b(?:mixed clothing|accessories)$")
# Words a wholesale title uses that no resale listing carries.
LOT_WORDS_RE = re.compile(r"\b(?:brand name|premium brand|sports brand)\b")
# One piece is listed in the singular; the plural finds lots of several.
SINGULAR = {
    "jackets": "jacket", "vests": "vest", "blazers": "blazer", "hoodies": "hoodie", "sweatshirts": "sweatshirt",
    "sweaters": "sweater", "jerseys": "jersey", "t-shirts": "t-shirt", "tops": "top", "blouses": "blouse",
    "shirts": "shirt", "dresses": "dress", "skirts": "skirt", "rompers": "romper", "kimonos": "kimono",
}
EBAY_SOLD_RE = re.compile(r"Sold\s+([A-Z][a-z]{2}) (\d{1,2}), (\d{4})")
EBAY_PRICE_RE = re.compile(r"\$([\d,]+\.\d{2})")


def search_query(theme: str) -> str | None:
    """What to type into a marketplace to find one piece of `theme`, or None when
    the theme is too vague to search."""
    if UNSEARCHABLE_RE.search(theme):
        return None
    words = LOT_WORDS_RE.sub(" ", theme).split()
    return " ".join([*words[:-1], SINGULAR.get(words[-1], words[-1])]) if words else None


def _usable(title: str, price: float, sold_at: date, today: date) -> bool:
    return bool(title) and 1 <= price <= 500 and 0 <= (today - sold_at).days <= MAX_AGE_DAYS


# --- eBay, through the seller's Chrome -----------------------------------------------


def parse_ebay_cards(cards: list, today: date) -> list[dict]:
    """The sold search results the extension read, as comps. A result whose price
    is hidden behind an accepted offer, or shown as a range, is left out."""
    comps = []
    seen = set()
    for card in cards:
        if not isinstance(card, dict) or card.get("offer"):
            continue
        listing_id = str(card.get("id") or "")
        sold = EBAY_SOLD_RE.fullmatch(str(card.get("caption") or "").strip())
        price = EBAY_PRICE_RE.fullmatch(str(card.get("price") or "").strip())
        if not listing_id.isdigit() or listing_id in seen or not sold or not price or sold[1] not in MONTHS:
            continue
        try:
            sold_at = date(int(sold[3]), MONTHS[sold[1]], int(sold[2]))
        except ValueError:
            continue
        title = re.sub(r"^new listing", "", str(card.get("title") or "").split("\n")[0], flags=re.I).strip()
        amount = float(price[1].replace(",", ""))
        if not _usable(title, amount, sold_at, today):
            continue
        seen.add(listing_id)
        comps.append({
            "url": f"https://www.ebay.com/itm/{listing_id}", "title": title[:200], "sold_at": sold_at.isoformat(),
            "price": amount, "marketplace": "eBay", "currency": "USD",
            "snippet": f"Sold {sold[1]} {int(sold[2])}, {sold[3]} for ${amount:.2f} on eBay, pre-owned, shipping not included.",
        })
    return comps


async def _read_ebay(queries: list[str]) -> dict:
    from vendoo_studio.services.extension_connection import extension_manager

    request_id = "sold:" + uuid.uuid4().hex
    waiter = extension_manager.register_wait(request_id)
    try:
        sent = await extension_manager.send_message({"type": "market.sold_listings", "payload": {
            "request_id": request_id, "marketplace": "ebay", "queries": queries,
        }})
        if not sent:
            return {}
        return await asyncio.wait_for(waiter, timeout=30 + EBAY_SECONDS_PER_SEARCH * len(queries))
    finally:
        extension_manager.cancel_wait(request_id)


def ebay_ready() -> bool:
    """Whether a connected Chrome extension new enough to read eBay is there to ask."""
    from vendoo_studio.services.extension_connection import extension_manager

    try:
        version = tuple(int(part) for part in (extension_manager.version or "").split("."))
    except ValueError:
        return False
    return extension_manager.connected and extension_manager.loop is not None and version >= EBAY_EXTENSION_VERSION


def ebay_sold(queries: list[str], today: date) -> dict[str, list[dict]]:
    """eBay's sold listings per query, for every search Chrome completed. Empty
    when Chrome is not connected. Called from the sourcing thread, never the
    server's event loop."""
    from vendoo_studio.services.extension_connection import extension_manager

    if not queries or not ebay_ready():
        return {}
    try:
        result = asyncio.run_coroutine_threadsafe(_read_ebay(queries), extension_manager.loop).result()
    except Exception as exc:  # the next refresh asks again
        log.warning("eBay sold listings were not read: %s", exc or type(exc).__name__)
        return {}
    if result.get("error"):
        log.warning("eBay sold listings stopped early: %s", result["error"])
    found = result.get("results")
    return {query: parse_ebay_cards(cards, today) for query, cards in found.items()
            if query in queries and isinstance(cards, list)} if isinstance(found, dict) else {}


# --- Poshmark ------------------------------------------------------------------------


def poshmark_listings(query: str, *, sold: bool) -> list[dict]:
    """One page of Poshmark's search, as the listing records the page is built from."""
    params = urlencode({"query": query, "availability": "sold_out" if sold else "available", "type": "listings"})
    request = urllib.request.Request(f"{POSHMARK_SEARCH}?{params}", headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urllib.request.urlopen(request, timeout=30) as response:
        page = response.read().decode("utf-8", "replace")
    match = re.search(r"window\.__INITIAL_STATE__\s*=\s*", page)
    if not match:
        raise ValueError("Poshmark's search page has no listing data")
    state, _ = json.JSONDecoder().raw_decode(page, match.end())
    listings = state["$_search"]["gridData"]["data"]
    return listings if isinstance(listings, list) else []


def _poshmark_listing(listing: object, status: str) -> tuple[str, str, float, dict] | None:
    """A pre-owned listing in `status` priced in USD: its link, title, price and stock record."""
    if not isinstance(listing, dict):
        return None
    inventory = listing.get("inventory")
    amount = listing.get("price_amount")
    if not isinstance(inventory, dict) or not isinstance(amount, dict):
        return None
    if inventory.get("status") != status or amount.get("currency_code") != "USD" or listing.get("condition") == "nwt":
        return None
    listing_id = str(listing.get("id") or "")
    try:
        price = float(amount.get("val"))
    except (TypeError, ValueError):
        return None
    if not re.fullmatch(r"[0-9a-f]{24}", listing_id):
        return None
    return f"https://poshmark.com/listing/{listing_id}", str(listing.get("title") or "").strip(), price, inventory


def parse_poshmark_sold(listings: list, today: date) -> list[dict]:
    comps = []
    for listing in listings:
        found = _poshmark_listing(listing, "sold_out")
        if not found:
            continue
        url, title, price, inventory = found
        try:
            sold_at = date.fromisoformat(str(inventory.get("status_changed_at") or "")[:10])
        except ValueError:
            continue
        if not _usable(title, price, sold_at, today):
            continue
        comps.append({
            "url": url, "title": title[:200], "sold_at": sold_at.isoformat(), "price": price,
            "marketplace": "Poshmark", "currency": "USD",
            "snippet": f"Sold on Poshmark {sold_at.isoformat()}, listed at ${price:.2f} when it sold. "
                       "An accepted offer may have been lower.",
        })
    return comps


def parse_poshmark_active(listings: list) -> list[dict]:
    active = []
    for listing in listings:
        found = _poshmark_listing(listing, "available")
        if not found:
            continue
        url, title, price, _ = found
        if title and 1 <= price <= 500:
            active.append({"url": url, "title": title[:200], "price": price, "marketplace": "Poshmark",
                           "currency": "USD", "snippet": f"For sale on Poshmark at ${price:.2f}."})
    return active
