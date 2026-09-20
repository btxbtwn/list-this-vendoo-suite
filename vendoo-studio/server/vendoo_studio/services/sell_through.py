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
import weakref
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
# ...but half of nothing is nothing. A cohort that sells at full ask, or whose
# discounts are not visible, still has to move a listing that has outlived the
# pattern, so every further cycle is worth at least this much.
MIN_OVERDUE_STEP = 0.05


@dataclass(frozen=True)
class SoldOutcome:
    """One closed sale, reduced to what pricing can learn from it."""

    category: str
    brand: str
    first_price: float
    sold_price: float
    days_listed: int | None
    # Whether ``first_price`` is a real asking price this sale moved away from.
    # An item bulk-imported after it sold carries one revision — Vendoo's final
    # price — so "sold at that price" is an artifact of the import, not a sale
    # at full ask, and counting it as 0% off drags the whole cohort to zero.
    discount_known: bool = True

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
    # None when too few of these sales show what they moved off — see
    # ``SoldOutcome.discount_known``. Time-to-sell still stands on its own.
    median_discount: float | None
    median_days: float | None
    discount_count: int = 0

    def describe(self) -> str:
        days = (
            f" after about {round(self.median_days)} days"
            if self.median_days is not None
            else ""
        )
        if self.median_discount is None:
            return f"Your {self.label} sell{days} ({self.count} sold)."
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
    # Only sales that show what they moved off can speak to discount; the rest
    # still time the market. A thin discount sample is left as None rather than
    # averaged in as zero, which would read as "these sell at full ask".
    told = [outcome for outcome in usable if outcome.discount_known]
    discount = _median([outcome.discount for outcome in told]) if len(told) >= MIN_COHORT else None
    days = _median([float(o.days_listed) for o in usable if o.days_listed is not None])
    if discount is None and days is None:
        return None
    return CohortStats(
        scope=scope,
        label=label,
        count=len(usable),
        median_discount=discount,
        median_days=days,
        discount_count=len(told),
    )


def pick_cohort(
    outcomes: list[SoldOutcome],
    *,
    category: str,
    brand: str,
) -> CohortStats | None:
    """The most specific group with enough closed sales behind it.

    Specific beats broad, but a group that can only time the market loses to a
    broader one that also knows what prices had to move — otherwise a category
    full of after-the-fact imports hides every discount the seller ever took.
    """
    found: list[CohortStats] = []
    leaf = category_leaf(category)
    if leaf:
        same_category = [o for o in outcomes if o.category == leaf]
        stats = cohort_stats(same_category, scope="category", label=leaf)
        if stats:
            if stats.median_discount is not None:
                return stats
            found.append(stats)
    name = str(brand or "").strip().lower()
    if name:
        same_brand = [o for o in outcomes if o.brand == name]
        stats = cohort_stats(same_brand, scope="brand", label=name.title())
        if stats:
            if stats.median_discount is not None:
                return stats
            found.append(stats)
    everything = cohort_stats(outcomes, scope="all", label="items")
    if everything and everything.median_discount is not None:
        return everything
    if found:
        return found[0]
    return everything


def target_discount(stats: CohortStats, age_days: int | None) -> float:
    """How far below the first asking price this listing should be by now.

    Before the cohort's typical time-to-sell, the target eases toward the
    discount those sales closed at. Past it, the listing has already outlived
    the pattern, so the target keeps stepping beyond that discount — by at
    least ``MIN_OVERDUE_STEP`` a cycle, so a cohort that sells at full ask (or
    one whose discounts are invisible) is not a reason to never cut a listing
    that is months past when its neighbours sold.
    """
    settled = stats.median_discount or 0.0
    if stats.median_days is None or stats.median_days <= 0 or age_days is None:
        return min(MAX_TOTAL_DISCOUNT, settled)
    pace = age_days / stats.median_days
    if pace <= 1.0:
        return min(MAX_TOTAL_DISCOUNT, settled * pace)
    step = max(settled * OVERDUE_STEP, MIN_OVERDUE_STEP)
    return min(MAX_TOTAL_DISCOUNT, settled + (pace - 1.0) * step)


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
    if already >= 0.5:
        age = f"{age} at {already:.0f}% off"
    overdue = (
        stats.median_days is not None
        and stats.median_days > 0
        and age_days is not None
        and age_days > stats.median_days
    )
    landed = (
        "well past that, so stepping it down."
        if overdue
        else "pricing it where those sales landed."
    )
    return price, f"{stats.describe()} This one is {age} — {landed}"


def _price_of(listing: Any) -> float:
    from vendoo_studio.services.price_drop import listing_price

    amount = listing_price(listing if isinstance(listing, dict) else None)
    return float(amount) if amount else 0.0


def _parse_moment(text: str) -> datetime | None:
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _days_between(listed: str, sold: str) -> int | None:
    start, end = _parse_moment(listed), _parse_moment(sold)
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


def _discount_is_evidence(
    *,
    first_price: float,
    sold_price: float,
    first_seen: datetime | None,
    sold_at: str,
) -> bool:
    """Whether this sale can say anything about how far a price had to move.

    Two ways it can. A closing price that differs from the first asking price
    is movement we can see — a drop Studio recorded, or an accepted offer below
    ask. Otherwise the asking price has to be one Studio held *before* the
    sale: an item bulk-imported afterwards carries only Vendoo's closing price,
    so "sold at that price" would be a tautology, not a sale at full ask.
    """
    if sold_price > 0 and first_price > 0 and abs(sold_price - first_price) > 0.005:
        return True
    if first_seen is None or not sold_at:
        return False
    sold_moment = _parse_moment(sold_at)
    if sold_moment is None:
        return False
    seen = first_seen if first_seen.tzinfo else first_seen.replace(tzinfo=UTC)
    return seen < sold_moment


# One whole-workspace scan is enough until something in it changes. The price
# drop dialog asks for this evidence on every open, and the answer only moves
# when a conversation or a revision does — see ``_evidence_fingerprint``.
_CACHE_LIMIT = 4
# Keyed weakly on the engine, so a workspace that goes away takes its evidence
# with it and no two databases can ever collide on a recycled key.
_outcome_cache: weakref.WeakKeyDictionary[Any, tuple[tuple, list[SoldOutcome]]] = (
    weakref.WeakKeyDictionary()
)
# SQLite binds each id in an IN clause as its own variable; older builds stop
# at 999 of them, and a seller with that many sold items is not exotic.
_ID_BATCH = 500


def _evidence_fingerprint(db) -> tuple:
    """A cheap stand-in for "the sold items or their prices changed"."""
    from sqlalchemy import func

    from vendoo_studio.models.conversation import Conversation
    from vendoo_studio.models.listing import ListingRevision

    convs = db.query(func.count(Conversation.id), func.max(Conversation.updated_at)).one()
    revs = db.query(func.count(ListingRevision.id), func.max(ListingRevision.created_at)).one()
    return (convs[0], str(convs[1]), revs[0], str(revs[1]))


def collect_outcomes(db, *, use_cache: bool = True) -> list[SoldOutcome]:
    """Every closed sale in the workspace, as pricing evidence.

    Vendoo records what an item sold for; Studio only keeps that once the item
    has been imported since the sale price was captured, so an item without one
    falls back to the price its listing carried when it sold.

    Only the columns this reads are loaded: a workspace of a thousand items
    holds far more listing JSON than a price suggestion needs to look at.
    """
    from vendoo_studio.models.conversation import Conversation
    from vendoo_studio.models.listing import ListingRevision
    from vendoo_studio.services.vendoo_import import parse_notes

    engine = db.get_bind() if use_cache else None
    fingerprint = _evidence_fingerprint(db) if use_cache else None
    if engine is not None:
        cached = _outcome_cache.get(engine)
        if cached and cached[0] == fingerprint:
            return list(cached[1])

    sold = [
        row
        for row in db.query(Conversation.id, Conversation.status, Conversation.notes).all()
        if str(row.status or "") == "sold"
        or str(parse_notes(row.notes).get("vendooStatus") or "") == "sold"
    ]
    if not sold:
        return _remember(engine, fingerprint, [])
    ids = [row.id for row in sold]
    revisions: dict[str, list[Any]] = {}
    for start in range(0, len(ids), _ID_BATCH):
        batch = ids[start : start + _ID_BATCH]
        rows = (
            db.query(
                ListingRevision.conversation_id,
                ListingRevision.listing_json,
                ListingRevision.created_at,
            )
            .filter(ListingRevision.conversation_id.in_(batch))
            .order_by(ListingRevision.created_at.asc())
            .all()
        )
        for row in rows:
            revisions.setdefault(row.conversation_id, []).append(row)

    outcomes: list[SoldOutcome] = []
    for conv in sold:
        history = revisions.get(conv.id) or []
        prices = [(_price_of(row.listing_json), row.listing_json, row.created_at) for row in history]
        priced = [(amount, listing, seen) for amount, listing, seen in prices if amount > 0]
        if not priced:
            continue
        first_price, _first, first_seen = priced[0]
        last_price, last, _last_seen = priced[-1]
        notes = parse_notes(conv.notes)
        sale = notes.get("vendooSale") if isinstance(notes.get("vendooSale"), dict) else {}
        try:
            sold_price = float(sale.get("price") or 0)
        except (TypeError, ValueError):
            sold_price = 0.0
        dates = notes.get("vendooDates") if isinstance(notes.get("vendooDates"), dict) else {}
        sold_at = str(dates.get("sold") or "")
        outcomes.append(
            SoldOutcome(
                category=category_leaf(last.get("category_path") if isinstance(last, dict) else ""),
                brand=str((last or {}).get("brand") or "").strip().lower(),
                first_price=first_price,
                sold_price=sold_price or last_price,
                days_listed=_days_between(str(dates.get("listed") or ""), sold_at),
                discount_known=_discount_is_evidence(
                    first_price=first_price,
                    sold_price=sold_price or last_price,
                    first_seen=first_seen,
                    sold_at=sold_at,
                ),
            )
        )
    return _remember(engine, fingerprint, outcomes)


def _remember(engine: Any, fingerprint: tuple | None, outcomes: list[SoldOutcome]):
    if engine is None:
        return outcomes
    if len(_outcome_cache) >= _CACHE_LIMIT and engine not in _outcome_cache:
        oldest = next(iter(_outcome_cache), None)
        if oldest is not None:
            _outcome_cache.pop(oldest, None)
    _outcome_cache[engine] = (fingerprint, outcomes)
    return list(outcomes)
