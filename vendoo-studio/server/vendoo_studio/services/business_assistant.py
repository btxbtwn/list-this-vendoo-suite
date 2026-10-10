"""The business assistant: questions about the whole shop, answered from Studio's data.

A listing's chat knows one item. This one is handed everything Studio holds
about the business on every question — each listing as a row, the same sales
and inventory totals Analytics shows, the boxes bought and what they returned,
the current buy list, ad spend, sale events, and sourcing checks — and answers
from that. The brief is read fresh each time, so an answer is never older than
the last Vendoo sync.

It only reads. Nothing here writes a listing, calls Vendoo, or reaches a
marketplace.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from vendoo_studio.models.assistant import AssistantMessage
from vendoo_studio.services.inventory_analytics import ANALYTICS_RANGES, AnalyticsItem

# Earlier turns sent back with a question, so a follow-up can lean on them.
HISTORY_MESSAGES = 20
# Room for the listing rows, in characters. Past it the oldest rows are left
# out and the brief says so; the totals above the table still count them.
LISTING_ROWS_BUDGET = 300_000
BRAND_GROUPS = 40
SOURCING_LOTS = 40

INSTRUCTIONS = (
    "You are the business assistant inside Vendoo Studio, talking to a reseller about their own shop. "
    "They sell clothing and similar goods on marketplaces such as eBay, Poshmark, Mercari, Depop and Etsy, "
    "cross-listed through Vendoo.\n\n"
    "Below is a snapshot, taken now, of everything Studio holds about the business. Answer from it.\n"
    "- Work figures out from the rows when no total is given, and check a total against the rows when both exist.\n"
    "- Say what a figure rests on when the data is partial: how many sales had a cost recorded, "
    "how many listings had a list date, and so on. Unknown is not zero.\n"
    "- When the snapshot cannot answer the question, say what is missing and where in Studio it gets recorded. "
    "Never invent a sale, a price, a cost or a date.\n"
    "- Profit is the sold price plus shipping the buyer paid, less fees, shipping the seller paid, and the item's cost.\n"
    "- Give advice when asked — what to source, reprice, discount or drop — and tie each point to the numbers behind it.\n"
    "- You only read. You cannot change a listing, a price or a setting, and you cannot list, delist or send anything. "
    "When the seller wants something changed, tell them where in Studio to do it.\n"
    "- Ids in the snapshot only tie rows together. Name a box by its store and title, never by its id.\n"
    "- Write plain English and lead with the answer. Use a table when comparing several things. Amounts are US dollars.\n"
)

_SALES_KEYS = ("range", "sell_through_rate", "sales", "previous", "periods", "marketplaces", "categories", "ads")
_LOT_KEYS = (
    "store", "title", "price", "pcs", "grade", "theme", "landed", "cog_per_pc", "resale_per_pc",
    "sell_through", "expected_revenue", "expected_profit", "roi", "downside_profit", "comps_count",
)
_ROW_HEADER = (
    "title | status | brand | category | asking | cost | sold_for | fees | profit | marketplace"
    " | listed | sold | days | box"
)


def list_messages(db: Session) -> list[AssistantMessage]:
    return db.query(AssistantMessage).order_by(AssistantMessage.created_at, AssistantMessage.id).all()


def add_message(db: Session, role: str, text: str, *, provider: str | None = None, model: str | None = None):
    row = AssistantMessage(role=role, text=text, provider=provider, model=model)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def clear_messages(db: Session) -> None:
    db.query(AssistantMessage).delete()
    db.commit()


def message_view(row: AssistantMessage) -> dict[str, Any]:
    created = row.created_at
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return {
        "id": row.id,
        "role": row.role,
        "text": row.text,
        "created_at": created.isoformat() if created else None,
    }


def build_messages(db: Session, question: str, *, now: datetime | None = None) -> list[dict]:
    """The prompt for ``question``: instructions, the brief, earlier turns, then the question.

    The seller's question must already be saved; it is the last turn read back.
    """
    earlier = [
        {"role": row.role, "content": row.text}
        for row in list_messages(db)[-(HISTORY_MESSAGES + 1):]
    ]
    if not earlier or earlier[-1] != {"role": "user", "content": question}:
        earlier.append({"role": "user", "content": question})
    # The instructions lead so a provider's prefix cache still hits when the figures move.
    return [{"role": "system", "content": f"{INSTRUCTIONS}\n{business_brief(db, now=now)}"}, *earlier]


def business_brief(db: Session, *, now: datetime | None = None) -> str:
    """Everything Studio knows about the business, as text a model can read."""
    from vendoo_studio.services import ad_spend, boxes, box_scout, scout
    from vendoo_studio.services.inventory_analytics import inventory_analytics, load_rows

    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    rows = load_rows(db)
    ranges = {
        range_id: inventory_analytics(db, range_id=range_id, now=clock, rows=rows)
        for range_id in ANALYTICS_RANGES
    }
    everything = ranges["all"]
    scout_sales = scout.outcomes(db)
    sections = [
        f"Today is {clock.date().isoformat()} (UTC). "
        f"Sales and statuses were last synced from Vendoo at {everything['last_updated_at'] or 'an unknown time'}.",
        _section("Inventory now", {
            **everything["inventory"],
            "aging_of_active_listings": [
                {key: bucket[key] for key in ("label", "count", "asking_value")} for bucket in everything["aging"]
            ],
            "sold_listings_missing_a_sale_date": everything["undated_sales"],
            "sold_listings_missing_some_figure": len(everything["incomplete_sales"]),
        }),
        *(
            _section(f"Sales, {_RANGE_LABELS[range_id]}", {
                **{key: payload[key] for key in _SALES_KEYS},
                "brands": payload["brands"][:BRAND_GROUPS],
            })
            for range_id, payload in ranges.items()
        ),
        _listing_rows(rows, clock),
        _section("Wholesale boxes bought, and what each has returned", boxes.results(db)),
        _sourcing(box_scout.read_state()),
        _section("Ad spend the seller recorded", [ad_spend.entry_view(row) for row in ad_spend.list_entries(db)]),
        _section("Sale events", _sale_events(db)),
        _section("Sourcing checks (is this worth buying?)", {
            "track_record": scout.track_record(db, scout_sales),
            "recent": [
                {key: check[key] for key in ("title", "asking_price", "estimate", "comps_count", "decision",
                                             "sold_price", "created_at")}
                for check in (scout.to_dict(row, scout_sales.get(row.id)) for row in scout.recent(db))
            ],
        }),
    ]
    return "\n\n".join(section for section in sections if section)


_RANGE_LABELS = {
    "7d": "last 7 days",
    "30d": "last 30 days",
    "90d": "last 90 days",
    "12m": "last 12 calendar months",
    "all": "all time",
}


def _section(title: str, payload: Any) -> str:
    if payload in (None, [], {}):
        return f"--- {title} ---\nNothing recorded."
    return f"--- {title} ---\n{json.dumps(payload, separators=(',', ':'), default=str)}"


def _listing_rows(rows: list[AnalyticsItem], now: datetime) -> str:
    """One line per listing, newest sales first, then what is still for sale."""
    lines: list[str] = []
    used = 0
    ordered = _ordered(rows)
    for item in ordered:
        line = _row(item, now)
        if used + len(line) > LISTING_ROWS_BUDGET:
            break
        lines.append(line)
        used += len(line) + 1
    title = f"--- Every listing ({len(rows)}) ---"
    if not rows:
        return f"{title}\nNo listings yet."
    left_out = len(ordered) - len(lines)
    note = (
        "`days` is days to sell for a sold listing and days listed so far for an active one. "
        "`box` is the id of the wholesale box it came from. Empty means not recorded."
    )
    if left_out:
        note += (
            f" {left_out} listings did not fit and are left out, oldest sales and drafts first;"
            " the totals above still count them."
        )
    return "\n".join([title, note, _ROW_HEADER, *lines])


def _ordered(rows: list[AnalyticsItem]) -> list[AnalyticsItem]:
    oldest = datetime.min.replace(tzinfo=UTC)
    sold = sorted(
        (item for item in rows if item.status == "sold"), key=lambda item: item.sold_at or oldest, reverse=True,
    )
    active = sorted(
        (item for item in rows if item.status == "active"), key=lambda item: item.listed_at or oldest,
    )
    rest = [item for item in rows if item.status not in {"sold", "active"}]
    return [*sold, *active, *rest]


def _row(item: AnalyticsItem, now: datetime) -> str:
    sold = item.status == "sold"
    days = item.days_listed
    if not sold and item.status == "active" and item.listed_at is not None:
        days = max(0, (now - item.listed_at).days)
    profit = item.profit if sold and item.has_cost and item.sold_price is not None else None
    return " | ".join([
        item.title.replace("|", "/").replace("\n", " "),
        item.status,
        item.brand.replace("|", "/"),
        item.category.replace("|", "/"),
        _amount(item.price or None),
        _amount(item.cost),
        _amount(item.sold_price),
        _amount(item.fees),
        _amount(profit),
        "" if item.marketplace == "unknown" else item.marketplace,
        item.listed_at.date().isoformat() if item.listed_at else "",
        item.sold_at.date().isoformat() if item.sold_at else "",
        "" if days is None else str(days),
        item.box_id or "",
    ])


def _amount(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}".rstrip("0").rstrip(".")


def _sourcing(state: dict) -> str:
    """The current buy list: what the seller told Sourcing, and what it would buy."""
    snapshot = state.get("snapshot")
    if not snapshot:
        return _section("Sourcing buy list", None)
    plan = snapshot.get("buy_list") or {}
    return _section("Sourcing buy list", {
        "updated_at": snapshot.get("updated_at"),
        "preferences": state.get("prefs"),
        "trending_terms": (state.get("trend") or {}).get("terms"),
        "budget": plan.get("budget"),
        "total": plan.get("total"),
        "expected_profit": plan.get("expected_profit"),
        "recommended_lots": [
            {key: lot.get(key) for key in _LOT_KEYS}
            for cart in plan.get("carts") or [] for lot in cart.get("lots") or []
        ][:SOURCING_LOTS],
    })


def _sale_events(db: Session) -> list[dict[str, Any]]:
    from vendoo_studio.models.sale_event import SaleEvent

    return [
        {
            "title": event.title,
            "marketplace": event.marketplace,
            "start_date": event.start_date.isoformat(),
            "end_date": event.end_date.isoformat(),
            "status": event.status,
            "discount_percent": event.discount_percent,
            "listings": len(event.items or []),
            "notes": event.notes or "",
        }
        for event in db.query(SaleEvent).order_by(SaleEvent.start_date.desc()).all()
    ]
