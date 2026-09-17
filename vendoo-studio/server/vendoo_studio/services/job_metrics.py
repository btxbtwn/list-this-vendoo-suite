"""Where automation time goes and which fields keep failing."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from vendoo_studio.models.conversation import utcnow
from vendoo_studio.models.fill_log import FillLogEntry
from vendoo_studio.models.job import JobEvent

FAILED_FILL_STATUSES = frozenset({"failed", "invalid", "not_found", "uncertain"})


def job_timing(db: Session, job_id: str) -> dict[str, Any]:
    """Per-step durations reported by the extension, with gaps between events as a fallback."""
    events = (
        db.query(JobEvent)
        .filter(JobEvent.job_id == job_id)
        .order_by(JobEvent.sequence.asc())
        .all()
    )
    steps: list[dict[str, Any]] = []
    previous_at = None
    for event in events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        if event.event_type in {"step_completed", "step_failed"}:
            reported = payload.get("duration_ms")
            elapsed = None
            if previous_at is not None and event.created_at is not None:
                elapsed = int((event.created_at - previous_at).total_seconds() * 1000)
            steps.append({
                "step": event.step or payload.get("step") or "",
                "status": "completed" if event.event_type == "step_completed" else "failed",
                "skipped": bool(payload.get("skipped")),
                "duration_ms": reported if isinstance(reported, (int, float)) else elapsed,
                "source": "extension" if isinstance(reported, (int, float)) else "event_gap",
            })
        if event.created_at is not None:
            previous_at = event.created_at
    total = sum(step["duration_ms"] or 0 for step in steps)
    slowest = sorted(steps, key=lambda step: -(step["duration_ms"] or 0))[:5]
    return {"job_id": job_id, "total_ms": total, "steps": steps, "slowest": slowest}


def fill_success_stats(db: Session, *, days: int = 30, limit: int = 50) -> dict[str, Any]:
    """Fill outcomes grouped by marketplace and field, worst success rate first."""
    since = utcnow() - timedelta(days=max(1, days))
    rows = db.query(FillLogEntry).filter(FillLogEntry.created_at >= since).all()
    grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"total": 0, "filled": 0, "failed": 0, "statuses": defaultdict(int)}
    )
    for row in rows:
        stats = grouped[(row.marketplace, row.field)]
        stats["total"] += 1
        stats["statuses"][row.status] += 1
        if row.status == "filled":
            stats["filled"] += 1
        elif row.status in FAILED_FILL_STATUSES:
            stats["failed"] += 1
    fields = []
    for (marketplace, field), stats in grouped.items():
        attempted = stats["filled"] + stats["failed"]
        fields.append({
            "marketplace": marketplace,
            "field": field,
            "total": stats["total"],
            "filled": stats["filled"],
            "failed": stats["failed"],
            "success_rate": round(stats["filled"] / attempted, 3) if attempted else None,
            "statuses": dict(stats["statuses"]),
        })
    fields.sort(key=lambda item: (item["success_rate"] if item["success_rate"] is not None else 2, -item["failed"]))
    by_marketplace: dict[str, dict[str, int]] = defaultdict(lambda: {"filled": 0, "failed": 0})
    for item in fields:
        by_marketplace[item["marketplace"]]["filled"] += item["filled"]
        by_marketplace[item["marketplace"]]["failed"] += item["failed"]
    return {
        "days": days,
        "entries": len(rows),
        "by_marketplace": {
            marketplace: {
                **counts,
                "success_rate": round(counts["filled"] / (counts["filled"] + counts["failed"]), 3)
                if counts["filled"] + counts["failed"]
                else None,
            }
            for marketplace, counts in by_marketplace.items()
        },
        "fields": fields[:limit],
    }
