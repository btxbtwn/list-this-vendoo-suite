"""What the seller's own sold items say a price drop should be.

The price-drop suggestion used to be constants — 10% off, 15%, a 1.35×
multiple on outside comps — none of which know anything about this seller's
inventory. This reads their own closed sales instead: how long items like this
one took to sell, and how far below the first asking price they ended up.

A cohort is the most specific group with enough closed sales to mean anything:
the same category leaf, else the same brand, else the whole inventory. Under
``MIN_COHORT`` sales the answer is noise, and the caller falls back to the
history-aware percentage.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Any

# Four sales is an anecdote; the fifth is the first hint of a pattern.
MIN_COHORT = 5
# A drop this deep in one step is a mistake, whatever the history says.
MAX_STEP_PERCENT = 35.0
# No suggestion ever prices below this share of the first asking price.
MAX_TOTAL_DISCOUNT = 0.6
# Past the typical time-to-sell, keep stepping: half the cohort's discount per
# further cycle, so a listing at triple the usual age is not merely "typical".
OVERDUE_STEP = 0.5


@dataclass(frozen=True)
class SoldOutcome:
    """One closed sale, reduced to what pricing can learn from it."""

    category: str
    brand: str
    first_price: float
    sold_price: float
    days_listed: int | None

    @property
    def discount(self) -> float:
        """Share off the first asking price, 0.0 when it sold at or above ask."""
        if self.first_price <= 0 or self.sold_price <= 0:
            return 0.0
        return max(0.0, 1.0 - self.sold_price / self.first_price)


@dataclass(frozen=True)
class CohortStats:
    """The pricing story a group of closed sales tells."""

    scope: str
    label: str
    count: int
    median_discount: float
    median_days: float | None

    def describe(self) -> str:
        days = (
            f" after about {round(self.median_days)} days"
            if self.median_days is not None
            else ""
        )
        return (
            f"Your {self.label} sell at {self.median_discount * 100:.0f}% off"
            f"{days} ({self.count} sold)."
        )


def category_leaf(value: Any) -> str:
    """The last segment of a category path, which is the part worth grouping on."""
    if isinstance(value, list):
        parts = [str(part).strip() for part in value if str(part).strip()]
        return parts[-1].lower() if parts else ""
    text = str(value or "").strip()
    return text.split(">")[-1].strip().lower()


def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def cohort_stats(outcomes: list[SoldOutcome], *, scope: str, label: str) -> CohortStats | None:
    """Median discount and time-to-sell, or None when the group is too thin."""
    usable = [outcome for outcome in outcomes if outcome.first_price > 0 and outcome.sold_price > 0]
    if len(usable) < MIN_COHORT:
        return None
    discount = _median([outcome.discount for outcome in usable])
    if discount is None:
        return None
    days = _median([float(o.days_listed) for o in usable if o.days_listed is not None])
    return CohortStats(
        scope=scope,
        label=label,
        count=len(usable),
        median_discount=discount,
        median_days=days,
    )


def pick_cohort(
    outcomes: list[SoldOutcome],
    *,
    category: str,
    brand: str,
) -> CohortStats | None:
    """The most specific group with enough closed sales behind it."""
    leaf = category_leaf(category)
    if leaf:
        same_category = [o for o in outcomes if o.category == leaf]
        stats = cohort_stats(same_category, scope="category", label=leaf)
        if stats:
            return stats
    name = str(brand or "").strip().lower()
    if name:
        same_brand = [o for o in outcomes if o.brand == name]
        stats = cohort_stats(same_brand, scope="brand", label=name.title())
        if stats:
            return stats
    return cohort_stats(outcomes, scope="all", label="items")


def target_discount(stats: CohortStats, age_days: int | None) -> float:
    """How far below the first asking price this listing should be by now.

    Before the cohort's typical time-to-sell, the target eases toward the
    discount those sales closed at. Past it, the listing has already outlived
    the pattern, so the target keeps stepping beyond that discount.
    """
    if stats.median_days is None or stats.median_days <= 0 or age_days is None:
        return stats.median_discount
    pace = age_days / stats.median_days
    if pace <= 1.0:
        return stats.median_discount * pace
    overdue = (pace - 1.0) * OVERDUE_STEP * stats.median_discount
    return min(MAX_TOTAL_DISCOUNT, stats.median_discount + overdue)


def history_suggestion(
    stats: CohortStats | None,
    *,
    current_price: float,
    first_price: float,
    age_days: int | None,
) -> tuple[int, str] | None:
    """A whole-dollar price grounded in the seller's own sales, and why.

    Returns None when there is no cohort, or when the listing already sits at
    or below where those sales closed — the caller keeps its small default step
    rather than cutting into a price the history does not ask it to cut.
    """
    if stats is None or current_price <= 0:
        return None
    base = first_price if first_price > 0 else current_price
    target = target_discount(stats, age_days)
    wanted = base * (1.0 - target)
    # The cap is a limit on the step, so round it *up* to a whole dollar —
    # truncating it would step further than the cap allows.
    cap = math.ceil(current_price * (1.0 - MAX_STEP_PERCENT / 100.0))
    price = max(math.floor(wanted), cap)
    if price < 1 or price >= current_price:
        return None
    already = max(0.0, 1.0 - current_price / base) * 100
    age = f"{age_days} days in" if age_days is not None else "still listed"
    return price, (
        f"{stats.describe()} This one is {age} at {already:.0f}% off — "
        f"pricing it where those sales landed."
    )


def _price_of(listing: Any) -> float:
    from vendoo_studio.services.price_drop import listing_price

    amount = listing_price(listing if isinstance(listing, dict) else None)
    return float(amount) if amount else 0.0


def _days_between(listed: str, sold: str) -> int | None:
    def parse(text: str) -> datetime | None:
        if not text:
            return None
        try:
            moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
        except ValueError:
            return None
        return moment if moment.tzinfo else moment.replace(tzinfo=UTC)

    start, end = parse(listed), parse(sold)
    if start is None or end is None:
        return None
    days = int((end - start).total_seconds() // 86_400)
    return days if days >= 0 else None


def listing_age_days(notes: str | None, *, now: datetime | None = None) -> int | None:
    """Days since this listing last went live on a marketplace."""
    from vendoo_studio.services.vendoo_import import parse_notes

    parsed = parse_notes(notes)
    dates = parsed.get("vendooDates") if isinstance(parsed.get("vendooDates"), dict) else {}
    listed = str(dates.get("listed") or "")
    if not listed:
        return None
    clock = (now or datetime.now(UTC)).isoformat()
    return _days_between(listed, clock)


def collect_outcomes(db) -> list[SoldOutcome]:
    """Every closed sale in the workspace, as pricing evidence.

    Vendoo records what an item sold for; Studio only keeps that once the item
    has been imported since the sale price was captured, so an item without one
    falls back to the price its listing carried when it sold.
    """
    from vendoo_studio.models.conversation import Conversation
    from vendoo_studio.models.listing import ListingRevision
    from vendoo_studio.services.vendoo_import import parse_notes

    sold = [
        conv
        for conv in db.query(Conversation).all()
        if str(conv.status or "") == "sold"
        or str(parse_notes(conv.notes).get("vendooStatus") or "") == "sold"
    ]
    if not sold:
        return []
    ids = [conv.id for conv in sold]
    revisions: dict[str, list[ListingRevision]] = {}
    rows = (
        db.query(ListingRevision)
        .filter(ListingRevision.conversation_id.in_(ids))
        .order_by(ListingRevision.created_at.asc())
        .all()
    )
    for row in rows:
        revisions.setdefault(row.conversation_id, []).append(row)

    outcomes: list[SoldOutcome] = []
    for conv in sold:
        history = revisions.get(conv.id) or []
        prices = [(_price_of(row.listing_json), row.listing_json) for row in history]
        priced = [(amount, listing) for amount, listing in prices if amount > 0]
        if not priced:
            continue
        first_price, _first = priced[0]
        last_price, last = priced[-1]
        notes = parse_notes(conv.notes)
        sale = notes.get("vendooSale") if isinstance(notes.get("vendooSale"), dict) else {}
        try:
            sold_price = float(sale.get("price") or 0)
        except (TypeError, ValueError):
            sold_price = 0.0
        dates = notes.get("vendooDates") if isinstance(notes.get("vendooDates"), dict) else {}
        outcomes.append(
            SoldOutcome(
                category=category_leaf(last.get("category_path") if isinstance(last, dict) else ""),
                brand=str((last or {}).get("brand") or "").strip().lower(),
                first_price=first_price,
                sold_price=sold_price or last_price,
                days_listed=_days_between(str(dates.get("listed") or ""), str(dates.get("sold") or "")),
            )
        )
    return outcomes
