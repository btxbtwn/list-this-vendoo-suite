"""Scout: "is this worth buying?" from a few photos taken while sourcing.

The photos go through the same photo analysis and sold-comps research a new
listing uses. The expected sale price is the median of the sold comps, and the
verdict weighs it, after marketplace fees, against the asking price. Nothing is
bought and nothing is listed: "Bought it" only starts a draft from the same
photos, with the analysis already done, and every check is kept so its estimate
can later be set against what the item really sold for.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import statistics
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from vendoo_studio.config import PHOTOS_DIR
from vendoo_studio.models.conversation import Conversation
from vendoo_studio.models.scout import ScoutCheck

log = logging.getLogger("vendoo_studio.scout")

MAX_PHOTOS = 8
# Fees and payment processing on each sale; the same figure the buy list uses.
FEES = 0.20
# Buy when the item should at least double the money and clear this much.
MIN_PROFIT = 10.0
# Below this, it is not worth the time to list.
PASS_PROFIT = 5.0
RECENT = 30
# An estimate within this share of the real sale counts as close.
CLOSE_ENOUGH = 0.25

_tasks: set[asyncio.Task] = set()


def create_check(db: Session, photos: list[dict], asking_price: float | None) -> ScoutCheck:
    """Save a check for photos already written by ``photos.process_bytes``."""
    check = ScoutCheck(
        status="checking",
        asking_price=asking_price,
        photos=[photo["stored_filename"] for photo in photos],
    )
    db.add(check)
    db.commit()
    db.refresh(check)
    return check


def start(check_id: str) -> None:
    """Run the check beside the request that asked for it."""
    task = asyncio.create_task(run_check(check_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def run_check(check_id: str) -> None:
    from vendoo_studio.database import SessionLocal
    from vendoo_studio.services.brave_search import item_fields, sold_comps_query
    from vendoo_studio.services.comp_research import research_sold_comps
    from vendoo_studio.services.listing_generate import (
        PhotoAnalysisError,
        analyze_photos_with_tag_retry,
        require_photo_analysis,
    )
    from vendoo_studio.services.listing_provider import get_photo_provider
    from vendoo_studio.services.price_drop import market_midpoint
    from vendoo_studio.services.sold_comps import parse_sold_comps

    db = SessionLocal()
    try:
        check = db.get(ScoutCheck, check_id)
        if check is None:
            return
        try:
            provider = get_photo_provider()
            if provider is None:
                raise RuntimeError("Connect ChatGPT, Cursor or MiMo in Settings to check items.")
            paths = [str(Path(PHOTOS_DIR) / name) for name in check.photos]
            try:
                evidence, analysis = require_photo_analysis(await analyze_photos_with_tag_retry(provider, paths))
            except PhotoAnalysisError as exc:
                raise RuntimeError("Studio couldn't make out the item. Try a clearer photo of the tag.") from exc
            check.analysis = analysis
            check.title = sold_comps_query(item_fields(analysis, evidence)) or None
            db.commit()
            comps = await research_sold_comps(analysis, evidence)
            report = parse_sold_comps(comps)
            check.comps = comps
            check.comps_count = len([comp for comp in report.comps if comp.price > 0]) if report else 0
            check.estimate = market_midpoint(report)
            check.status = "done"
        except Exception as exc:
            log.exception("scout check %s failed", check_id)
            check.status = "failed"
            check.error = str(exc) or "The check failed. Try again."
        db.commit()
    finally:
        db.close()


def verdict(estimate: float | None, asking: float | None) -> dict[str, Any]:
    """What the item should bring in after fees, the most worth paying, and buy or pass."""
    if estimate is None:
        return {"net": None, "pay_up_to": None, "profit": None, "verdict": "unsure"}
    net = round(estimate * (1 - FEES), 2)
    pay_up_to = float(int(net / 2))
    if asking is None:
        return {"net": net, "pay_up_to": pay_up_to, "profit": None, "verdict": None}
    profit = round(net - asking, 2)
    if profit >= MIN_PROFIT and net >= 2 * asking:
        call = "buy"
    elif profit < PASS_PROFIT:
        call = "pass"
    else:
        call = "maybe"
    return {"net": net, "pay_up_to": pay_up_to, "profit": profit, "verdict": call}


def set_asking_price(db: Session, check: ScoutCheck, asking: float | None) -> ScoutCheck:
    check.asking_price = asking
    db.commit()
    db.refresh(check)
    return check


def decide(db: Session, check: ScoutCheck, decision: str) -> ScoutCheck:
    """Record the decision. Bought starts a draft from the same photos and analysis."""
    if decision not in {"bought", "passed"}:
        raise ValueError(decision)
    if decision == "bought" and not check.conversation_id:
        check.conversation_id = _start_listing(db, check).id
    check.decision = decision
    check.decided_at = datetime.now(UTC)
    db.commit()
    db.refresh(check)
    return check


def _start_listing(db: Session, check: ScoutCheck) -> Conversation:
    import json

    from vendoo_studio.repositories.queries import ConversationRepo

    repo = ConversationRepo(db)
    notes = json.dumps({"cog": f"{check.asking_price:g}"}) if check.asking_price is not None else None
    conv = repo.create(title=check.title or "New Listing", notes=notes)
    for name in check.photos:
        source = Path(PHOTOS_DIR) / name
        if not source.is_file():
            continue
        # A copy, so deleting the listing leaves the check's photos alone.
        copy = f"{uuid.uuid4().hex}{source.suffix}"
        shutil.copyfile(source, Path(PHOTOS_DIR) / copy)
        repo.add_photo(
            conv_id=conv.id,
            original_filename=name,
            stored_filename=copy,
            mime_type=_mime(source.suffix),
            size_bytes=source.stat().st_size,
        )
    if check.analysis:
        # Generation reuses a photo analysis it finds in the chat instead of asking again.
        repo.add_message(conv.id, "system", check.analysis)
    return conv


def _mime(suffix: str) -> str:
    return {
        ".png": "image/png",
        ".webp": "image/webp",
        ".heic": "image/heic",
        ".heif": "image/heif",
    }.get(suffix.lower(), "image/jpeg")


def recent(db: Session) -> list[ScoutCheck]:
    return db.query(ScoutCheck).order_by(ScoutCheck.created_at.desc()).limit(RECENT).all()


def outcomes(db: Session) -> dict[str, float]:
    """Sold price for each check whose listing has sold."""
    from vendoo_studio.services.inventory_analytics import load_rows

    linked = {
        conv_id: check_id
        for check_id, conv_id in db.query(ScoutCheck.id, ScoutCheck.conversation_id)
        .filter(ScoutCheck.conversation_id.isnot(None))
        .all()
    }
    if not linked:
        return {}
    return {
        linked[row.conversation_id]: row.sold_price
        for row in load_rows(db)
        if row.conversation_id in linked and row.status == "sold" and row.sold_price
    }


def track_record(db: Session, sold: dict[str, float] | None = None) -> dict[str, Any]:
    """How close the estimates have come to real sales."""
    sold = outcomes(db) if sold is None else sold
    checks = db.query(ScoutCheck.id, ScoutCheck.estimate, ScoutCheck.decision).all()
    ratios = [sold[cid] / estimate for cid, estimate, _ in checks if cid in sold and estimate]
    return {
        "checks": len(checks),
        "bought": sum(1 for *_rest, decision in checks if decision == "bought"),
        "sold": len(ratios),
        "median_ratio": round(statistics.median(ratios), 2) if ratios else None,
        "close": sum(1 for ratio in ratios if abs(ratio - 1) <= CLOSE_ENOUGH),
    }


def to_dict(check: ScoutCheck, sold_price: float | None = None) -> dict[str, Any]:
    return {
        "id": check.id,
        "status": check.status,
        "asking_price": check.asking_price,
        "photo_urls": [f"/api/scout/{check.id}/photos/{index}" for index in range(len(check.photos or []))],
        "title": check.title,
        "estimate": check.estimate,
        "comps_count": check.comps_count,
        "comps": check.comps,
        "error": check.error,
        "decision": check.decision,
        "conversation_id": check.conversation_id,
        "sold_price": sold_price,
        "created_at": _iso(check.created_at),
        **verdict(check.estimate, check.asking_price),
    }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()
