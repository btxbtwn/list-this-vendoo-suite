"""Price-only markdown for aging listings.

Keeps title, description, and categories. Suggests a cut from live sold comps
and prior ``price_drop`` revisions, then applies a confirmed whole-dollar price.
"""

from __future__ import annotations

import copy
import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from typing import Any

from vendoo_studio.models.listing import ListingRevision
from vendoo_studio.services.brave_search import item_fields
from vendoo_studio.services.comp_research import comps_search_available, research_sold_comps
from vendoo_studio.services.sold_comps import (
    MIN_CONFIDENT_COMPS,
    SoldCompsReport,
    extract_price,
    parse_sold_comps,
    trim_outliers,
)

PRICE_DROP_SOURCE = "price_drop"
DEFAULT_PERCENT = 15
RECENT_DROP_DAYS = 7
PERCENT_OPTIONS = (10, 15, 20)
_RANGE_RE = re.compile(
    r"\$\s*(\d{1,4}(?:\.\d{1,2})?)\s*(?:[-–—]|to)\s*\$?\s*(\d{1,4}(?:\.\d{1,2})?)",
    re.I,
)


@dataclass(frozen=True)
class PriceDropEvent:
    from_price: float
    to_price: float
    percent: float
    created_at: datetime | None
    revision_id: str


def listing_price(listing: dict | None) -> float | None:
    if not isinstance(listing, dict):
        return None
    raw = listing.get("price")
    if isinstance(raw, (int, float)):
        amount = float(raw)
    else:
        amount = extract_price(str(raw or ""))
        if amount is None:
            try:
                amount = float(str(raw or "").replace("$", "").replace(",", "").strip())
            except (TypeError, ValueError):
                return None
    if amount <= 0:
        return None
    return amount


def whole_dollars(amount: float) -> int:
    return max(1, int(round(amount)))


def price_after_percent(current: float, percent: float) -> int:
    return whole_dollars(current * (1.0 - percent / 100.0))


def fields_from_listing(listing: dict | None) -> dict[str, str]:
    """Build a sold-comps search identity from the current listing JSON."""
    if not isinstance(listing, dict):
        return {}
    evidence: dict[str, Any] = {}
    brand = str(listing.get("brand") or "").strip()
    if brand:
        evidence["brand"] = brand
    path = listing.get("category_path")
    if isinstance(path, list):
        path = " > ".join(str(part).strip() for part in path if str(part).strip())
    leaf = str(path or "").split(">")[-1].strip()
    if leaf:
        evidence["category"] = leaf
    size = listing.get("size")
    if size is None and isinstance(listing.get("ebay_specifics"), dict):
        size = listing["ebay_specifics"].get("size")
    size_text = str(size or "").strip()
    if size_text:
        evidence["size"] = size_text
    color = listing.get("primaryColor") or listing.get("primary_color") or listing.get("color")
    color_text = str(color or "").strip()
    if color_text:
        evidence["color"] = color_text
    return item_fields(None, evidence)


def first_listed_price(revisions: list[ListingRevision]) -> float | None:
    """Oldest recorded price on this listing (seed for cumulative drop)."""
    first: float | None = None
    for revision in reversed(revisions):
        amount = listing_price(revision.listing_json if isinstance(revision.listing_json, dict) else None)
        if amount is not None:
            first = amount
            break
    return first


def price_drop_history(revisions: list[ListingRevision]) -> list[PriceDropEvent]:
    """Prior Drop-price applies, newest first."""
    by_id = {revision.id: revision for revision in revisions}
    # Newest-first input; walk oldest→newest so parent lookup can fall back.
    chronological = list(reversed(revisions))
    previous: ListingRevision | None = None
    events: list[PriceDropEvent] = []
    for revision in chronological:
        if revision.source != PRICE_DROP_SOURCE:
            previous = revision
            continue
        to_price = listing_price(revision.listing_json if isinstance(revision.listing_json, dict) else None)
        parent = by_id.get(revision.parent_revision_id) if revision.parent_revision_id else None
        from_listing = parent.listing_json if parent and isinstance(parent.listing_json, dict) else None
        if from_listing is None and previous is not None:
            from_listing = previous.listing_json if isinstance(previous.listing_json, dict) else None
        from_price = listing_price(from_listing)
        previous = revision
        if to_price is None or from_price is None or to_price >= from_price:
            continue
        percent = round((1.0 - to_price / from_price) * 100.0, 1)
        events.append(
            PriceDropEvent(
                from_price=from_price,
                to_price=to_price,
                percent=percent,
                created_at=revision.created_at,
                revision_id=revision.id,
            )
        )
    events.reverse()
    return events


def suggest_percent(history: list[PriceDropEvent], *, now: datetime | None = None) -> tuple[int, str]:
    """History-aware default percent and a short reason for the dialog."""
    clock = now or datetime.now(UTC)
    if history:
        latest = history[0]
        created = latest.created_at
        if created is not None:
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            if clock - created <= timedelta(days=RECENT_DROP_DAYS):
                return 10, "Recent drop within 7 days — suggesting a smaller cut."
        if len(history) >= 3:
            return 5, "Several prior drops — suggesting a small step."
        if len(history) >= 2:
            return 10, "Already dropped twice — suggesting 10%."
    return DEFAULT_PERCENT, "Default 15% markdown."


def market_midpoint(report: SoldCompsReport | None) -> float | None:
    """Median of the sold listings, or a stated range when the search itemized none.

    Fewer than MIN_CONFIDENT_COMPS listings is one or two sales, not a market:
    the median is that sale, so the drop falls back to the history-aware percent.
    Wild prices are dropped first — see trim_outliers.
    """
    if report is None:
        return None
    prices = [comp.price for comp in report.comps if comp.price > 0]
    if prices:
        if len(prices) < MIN_CONFIDENT_COMPS:
            return None
        return float(statistics.median(trim_outliers(prices)))
    match = _RANGE_RE.search(report.market or "")
    if not match:
        match = _RANGE_RE.search(report.note or "")
    if match:
        lo, hi = float(match.group(1)), float(match.group(2))
        return (lo + hi) / 2.0
    single = extract_price(report.market or "")
    return single


def comps_formula_price(comps_text: str | None) -> tuple[float | None, int | None, SoldCompsReport | None]:
    """Market midpoint and listing target (market × 1.35, whole dollars)."""
    report = parse_sold_comps(comps_text)
    market = market_midpoint(report)
    if market is None:
        return None, None, report
    return market, whole_dollars(market * 1.35), report


def apply_price_to_listing(listing: dict, new_price: float) -> dict:
    """Copy listing with updated price; keep Poshmark original at the higher was-price."""
    updated = copy.deepcopy(listing)
    old = listing_price(updated)
    target = whole_dollars(new_price)
    updated["price"] = target
    specifics = updated.get("poshmark_specifics")
    if not isinstance(specifics, dict):
        specifics = {}
        updated["poshmark_specifics"] = specifics
    try:
        original = float(specifics.get("originalPrice") or 0)
    except (TypeError, ValueError):
        original = 0.0
    specifics["originalPrice"] = whole_dollars(max(original, old or 0, target))
    return updated


def event_payload(event: PriceDropEvent) -> dict[str, Any]:
    created = event.created_at
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return {
        "from_price": event.from_price,
        "to_price": event.to_price,
        "percent": event.percent,
        "created_at": created.isoformat() if created else "",
        "revision_id": event.revision_id,
    }


async def build_preview(
    listing: dict,
    revisions: list[ListingRevision],
    *,
    analysis_text: str | None = None,
    run_comps: bool = True,
) -> dict[str, Any]:
    current = listing_price(listing)
    if current is None:
        raise ValueError("Listing has no price to drop")

    history = price_drop_history(revisions)
    suggested_percent, reason = suggest_percent(history)
    prices_by_percent = {
        str(percent): price_after_percent(current, percent)
        for percent in PERCENT_OPTIONS
    }
    # History may suggest 5%, which is not a chip — still include its target.
    if str(suggested_percent) not in prices_by_percent:
        prices_by_percent[str(suggested_percent)] = price_after_percent(current, suggested_percent)

    comps_text = ""
    comps_available = comps_search_available()
    market: float | None = None
    comps_target: int | None = None
    report: SoldCompsReport | None = None
    if run_comps and comps_available:
        evidence = fields_from_listing(listing)
        comps_text = await research_sold_comps(analysis_text, evidence)
        market, comps_target, report = comps_formula_price(comps_text)

    percent_price = price_after_percent(current, suggested_percent)
    suggested_price = percent_price
    suggested_mode = "percent"
    # Prefer comps when they ask for a deeper cut than the history-aware %.
    if comps_target is not None and comps_target < current and comps_target <= percent_price:
        suggested_price = comps_target
        suggested_mode = "comps"
        reason = (
            f"{reason} Live comps target ${comps_target} (market × 1.35) — "
            "using that as the suggestion."
        )

    first_price = first_listed_price(revisions) or current
    return {
        "current_price": current,
        "first_price": first_price,
        "suggested_percent": suggested_percent,
        "suggested_price": suggested_price,
        "suggested_mode": suggested_mode,
        "suggested_reason": reason,
        "percent_options": list(PERCENT_OPTIONS),
        "prices_by_percent": prices_by_percent,
        "comps": {
            "available": comps_available,
            "text": comps_text,
            "market": (report.market if report else "") or "",
            "market_midpoint": market,
            "target_price": comps_target,
            "source": (report.source if report else "") or "",
            "query": (report.query if report else "") or "",
        },
        "history": [event_payload(event) for event in history],
    }
