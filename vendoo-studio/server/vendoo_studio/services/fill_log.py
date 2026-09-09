from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from vendoo_studio.config import FILL_LOGS_DIR
from vendoo_studio.models.fill_log import FillLogEntry
from vendoo_studio.models.job import Job
from vendoo_studio.repositories.queries import FillLogRepo, RegistryRepo

LOGGER = logging.getLogger("vendoo_studio.fill_log")

STATUSES = ("filled", "skipped", "not_found", "failed", "uncertain", "new")
MAX_ENTRIES = 200
MAX_PREVIEW = 80


def preview_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        text = ", ".join(str(item) for item in value)
    else:
        text = str(value)
    compact = " ".join(text.split())
    if len(compact) > MAX_PREVIEW:
        return compact[: MAX_PREVIEW - 3] + "..."
    return compact


def empty_summary() -> dict[str, int]:
    return {status: 0 for status in STATUSES}


def summarize(entries: list[dict] | list[FillLogEntry]) -> dict[str, int]:
    counts = empty_summary()
    for entry in entries:
        status = entry["status"] if isinstance(entry, dict) else entry.status
        if status in counts:
            counts[status] += 1
    return counts


def sanitize_entries(payload: dict | None) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get("entries")
    if not isinstance(raw, list):
        return []

    cleaned = []
    for item in raw[:MAX_ENTRIES]:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        status = str(item.get("status") or "").strip()
        if not field or status not in STATUSES:
            continue
        cleaned.append({
            "field": field[:120],
            "status": status,
            "reason": str(item.get("reason") or "")[:240],
            "selector": str(item.get("selector") or "")[:300],
            "value_preview": preview_value(item.get("value_preview") or item.get("value")),
            "marketplace": str(item.get("marketplace") or payload.get("marketplace") or "unknown")[:40],
        })
    return cleaned


def render_markdown(job: Job, grouped: dict[str, list[FillLogEntry]]) -> str:
    title = ""
    if isinstance(job.listing_snapshot, dict):
        title = preview_value(job.listing_snapshot.get("title") or "")
    lines = [
        f"# Fill log — {title or job.id}",
        "",
        f"- Job: `{job.id}`",
        f"- Listing: `{job.conversation_id}`",
        f"- Status: `{job.status}`",
        "",
    ]
    if not grouped:
        lines.append("_No fill results recorded yet._")
        lines.append("")
        return "\n".join(lines)

    for marketplace, entries in grouped.items():
        counts = summarize(entries)
        lines.append(f"## {marketplace}")
        lines.append("")
        lines.append(
            f"filled {counts['filled']} · skipped {counts['skipped']} · "
            f"not found {counts['not_found']} · failed {counts['failed']} · "
            f"uncertain {counts['uncertain']} · new {counts['new']}"
        )
        lines.append("")
        for status in STATUSES:
            matching = [entry for entry in entries if entry.status == status]
            if not matching:
                continue
            heading = {
                "filled": "Filled",
                "skipped": "Not filled (no listing value)",
                "not_found": "Did not work — field missing",
                "failed": "Did not work",
                "uncertain": "Uncertain (typed fallback)",
                "new": "New fields on the form",
            }[status]
            lines.append(f"### {heading}")
            lines.append("")
            for entry in matching:
                extra = []
                if entry.value_preview:
                    extra.append(f"`{entry.value_preview}`")
                if entry.reason:
                    extra.append(entry.reason)
                if entry.selector:
                    extra.append(f"`{entry.selector}`")
                suffix = f" — {' — '.join(extra)}" if extra else ""
                lines.append(f"- {entry.field}{suffix}")
            lines.append("")
    return "\n".join(lines)


class FillLogService:
    def __init__(self, db: Session):
        self._db = db
        self._repo = FillLogRepo(db)
        self._registry = RegistryRepo(db)

    def save_step(self, job: Job, step: str, payload: dict | None) -> list[FillLogEntry]:
        entries = sanitize_entries(payload)
        if not entries:
            return []

        marketplace = str((payload or {}).get("marketplace") or "").strip()
        if not marketplace:
            marketplace = entries[0]["marketplace"]

        saved = self._repo.replace_step(
            job_id=job.id,
            conversation_id=job.conversation_id,
            step=step,
            marketplace=marketplace,
            entries=entries,
        )
        category_path = None
        if isinstance(job.listing_snapshot, dict):
            category_path = job.listing_snapshot.get("category_path") or None
        self._update_registry(marketplace, category_path, entries)
        self.write_markdown(job)
        counts = summarize(saved)
        LOGGER.info(
            "fill log job=%s step=%s marketplace=%s filled=%s skipped=%s not_found=%s failed=%s uncertain=%s new=%s",
            job.id,
            step,
            marketplace,
            counts["filled"],
            counts["skipped"],
            counts["not_found"],
            counts["failed"],
            counts["uncertain"],
            counts["new"],
        )
        return saved

    def clear_job(self, job_id: str) -> None:
        self._repo.delete_for_job(job_id)
        path = self.log_path(job_id)
        if path.exists():
            path.unlink()

    def report_for_job(self, job: Job) -> dict:
        entries = self._repo.list_for_job(job.id)
        grouped_models: dict[str, list[FillLogEntry]] = {}
        for entry in entries:
            grouped_models.setdefault(entry.marketplace, []).append(entry)

        by_marketplace = {}
        for marketplace, models in grouped_models.items():
            by_marketplace[marketplace] = {
                "summary": summarize(models),
                "entries": [_entry_dict(entry) for entry in models],
            }
        return {
            "job_id": job.id,
            "conversation_id": job.conversation_id,
            "summary": summarize(entries),
            "by_marketplace": by_marketplace,
            "log_path": str(self.log_path(job.id)) if entries else None,
        }

    def write_markdown(self, job: Job) -> Path:
        entries = self._repo.list_for_job(job.id)
        grouped: dict[str, list[FillLogEntry]] = {}
        for entry in entries:
            grouped.setdefault(entry.marketplace, []).append(entry)
        path = self.log_path(job.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown(job, grouped), encoding="utf-8")
        return path

    def log_path(self, job_id: str) -> Path:
        safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "", job_id) or "job"
        return Path(FILL_LOGS_DIR) / f"{safe_id}.md"

    def _update_registry(self, marketplace: str, category_path: str | None, entries: list[dict]) -> None:
        for entry in entries:
            label = entry["field"]
            selector = entry.get("selector") or ""
            status = entry["status"]
            if status == "new":
                self._registry.ensure_field(
                    marketplace=marketplace,
                    field_label=label,
                    selector=selector,
                    category_path=category_path,
                )
                continue
            if status in {"filled", "uncertain", "not_found", "failed"} and selector:
                self._registry.record_fill_result(
                    marketplace=marketplace,
                    field_label=label,
                    selector=selector,
                    success=status == "filled",
                    category_path=category_path,
                )


def _entry_dict(entry: FillLogEntry) -> dict:
    return {
        "id": entry.id,
        "step": entry.step,
        "marketplace": entry.marketplace,
        "field": entry.field,
        "status": entry.status,
        "reason": entry.reason or "",
        "selector": entry.selector or "",
        "value_preview": entry.value_preview or "",
        "created_at": entry.created_at.isoformat() if entry.created_at else "",
    }
