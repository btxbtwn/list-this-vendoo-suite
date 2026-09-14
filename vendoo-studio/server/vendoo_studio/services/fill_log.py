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

STATUSES = ("filled", "skipped", "not_found", "invalid", "failed", "uncertain", "new")
FILLABLE_STATUSES = ("skipped", "new", "invalid", "failed", "uncertain", "not_found")
MAX_ENTRIES = 200
MAX_PREVIEW = 80
MAX_PATCH_FIELDS = 50
MAX_FILL_FIELDS = 200
# Marketplace descriptions (esp. Etsy ~10k) routinely exceed a few hundred chars.
MAX_PATCH_VALUE = 10_000

GENERAL_LISTING_KEYS = {
    "title": "title",
    "description": "description",
    "price": "price",
    "listing price": "price",
    "buy it now price": "price",
    "cost": "cost",
    "cost of goods": "cost",
    "quantity": "quantity",
    "brand": "brand",
    "condition": "condition",
    "primary color": "primaryColor",
    "color": "primaryColor",
    "secondary color": "secondaryColor",
    "size": "size",
    "us size": "size",
    "sku": "sku",
    "category": "category_path",
    "tags": "tags",
    "labels": "labels",
    "vendoo labels": "labels",
    "notes": "notes",
    "internal notes": "notes",
    "vendoo internal notes": "notes",
}

FIELD_LOOKUP_ALIASES = {
    "listing price": "price",
    "buy it now price": "price",
    "cost of goods": "cost",
    "us size": "size",
    "vendoo labels": "labels",
    "internal notes": "notes",
    "vendoo internal notes": "notes",
    "primary color": "color",
    "when was it made": "when made",
    "who made it": "who made",
    "starting price": "starting price",
    "return payed by": "return paid by",
}


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
        cleaned_item = {
            "field": field[:120],
            "status": status,
            "reason": str(item.get("reason") or "")[:240],
            "selector": str(item.get("selector") or "")[:300],
            "value_preview": preview_value(item.get("value_preview") or item.get("value")),
            "marketplace": str(item.get("marketplace") or payload.get("marketplace") or "unknown")[:40],
        }
        entry_id = str(item.get("id") or "").strip()[:40]
        if entry_id:
            cleaned_item["id"] = entry_id
        cleaned.append(cleaned_item)
    return cleaned


def normalize_field_label(value: str) -> str:
    key = str(value or "").strip()
    key = re.sub(r"^(ebay|etsy|poshmark|mercari|depop)\s+", "", key, flags=re.IGNORECASE)
    key = re.sub(r"[*?]+", " ", key)
    key = re.sub(r"\s+", " ", key).strip().lower()
    return key


def field_lookup_key(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^(ebay|etsy|poshmark|mercari|depop)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return FIELD_LOOKUP_ALIASES.get(text, text)


def _stringify_listing_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _value_from_record(record: dict | None, key: str) -> Any:
    if not isinstance(record, dict) or not key:
        return None
    from vendoo_studio.services.registry import label_to_json_key

    json_key = label_to_json_key(key)
    mapped = GENERAL_LISTING_KEYS.get(key)
    color_keys = {"color", "primary color"}
    for candidate, value in record.items():
        candidate_key = field_lookup_key(str(candidate))
        if candidate_key == key or (key in color_keys and candidate_key in color_keys):
            return value
        if str(candidate) == json_key or (mapped and str(candidate) == mapped):
            return value
    if json_key and json_key in record:
        return record.get(json_key)
    if mapped and mapped in record:
        return record.get(mapped)
    nested = record.get("category_specifics")
    if isinstance(nested, dict) and nested is not record:
        found = _value_from_record(nested, key)
        if found is not None:
            return found
    nested = record.get("marketplaceSpecifics") or record.get("marketplace_specifics")
    if isinstance(nested, dict) and nested is not record:
        return _value_from_record(nested, key)
    return None


def listing_value_for_field(listing: dict, marketplace: str, field: str) -> str:
    source = listing if isinstance(listing, dict) else {}
    marketplace = str(marketplace or "general").strip().lower()
    key = field_lookup_key(field)
    value: Any = None
    if marketplace in {"", "general", "unknown"}:
        value = _value_from_record(source, key)
    else:
        specifics = source.get(f"{marketplace}_specifics")
        value = _value_from_record(specifics if isinstance(specifics, dict) else {}, key)
        if value is None and key == "when made":
            ebay_specifics = source.get("ebay_specifics")
            value = _value_from_record(
                ebay_specifics if isinstance(ebay_specifics, dict) else {},
                "year manufactured",
            )
        if value is None:
            value = _value_from_record(source, key)
    result = _stringify_listing_value(value)
    if marketplace == "poshmark" and key == "category":
        from vendoo_studio.services.registry import map_poshmark_category_path
        return map_poshmark_category_path(result or str(source.get("category_path") or ""), source)
    if marketplace == "mercari" and key == "category":
        from vendoo_studio.services.registry import map_mercari_category_path
        return map_mercari_category_path(result or str(source.get("category_path") or ""), source)
    if result:
        if marketplace == "ebay" and key == "year manufactured" and re.match(
            r"^(d|n/?a|n\.a\.?|does not apply|none|unknown|-+)$",
            result,
            flags=re.I,
        ):
            return ""
        return result
    return ""


def extract_missing_fields(text: str) -> list[dict] | None:
    if not text or text.lstrip().lower().startswith("error:"):
        return None

    candidates: list[str] = []
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        candidates.append(fenced.group(1).strip())
    stripped = text.strip()
    if stripped:
        candidates.append(stripped)
    match = re.search(r"\{[\s\S]*\}", text) or re.search(r"\[[\s\S]*\]", text)
    if match:
        candidates.append(match.group().strip())

    import json

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        rows = None
        if isinstance(parsed, dict) and isinstance(parsed.get("missing_fields"), list):
            rows = parsed["missing_fields"]
        elif isinstance(parsed, list):
            rows = parsed
        if not rows:
            continue
        cleaned: list[dict] = []
        for item in rows:
            if not isinstance(item, dict) or item.get("op"):
                cleaned = []
                break
            field = str(item.get("field") or "").strip()
            value = item.get("value")
            if not field or value is None or str(value).strip() == "":
                continue
            cleaned.append({
                "marketplace": str(item.get("marketplace") or "general").strip().lower() or "general",
                "field": field,
                "value": value,
            })
        if cleaned:
            return cleaned[:MAX_PATCH_FIELDS]
    return None


def summarize_missing_fields(patches: list[dict]) -> str:
    market_labels = {
        "general": "Vendoo",
        "ebay": "eBay",
        "etsy": "Etsy",
        "poshmark": "Poshmark",
        "mercari": "Mercari",
        "depop": "Depop",
        "facebook": "Facebook",
        "shopify": "Shopify",
    }
    lines: list[str] = []
    for patch in patches or []:
        field = str(patch.get("field") or "").strip()
        value = patch.get("value")
        if not field or value is None:
            continue
        if isinstance(value, list):
            text = ", ".join(str(part).strip() for part in value if str(part).strip())
        else:
            text = str(value).strip()
        if not text:
            continue
        if len(text) > MAX_PREVIEW:
            text = text[: MAX_PREVIEW - 1] + "…"
        market = str(patch.get("marketplace") or "general").strip().lower() or "general"
        label = market_labels.get(market) or market.replace("_", " ").title()
        lines.append(f"{label} / {field}: {text}")
    if not lines:
        return "Saved leftover field values to the listing. Review them in Fields, then Fill on Vendoo."
    if len(lines) == 1:
        return f"Ready to fill on Vendoo — {lines[0]}."
    bullet = "\n".join(f"- {line}" for line in lines[:MAX_PATCH_FIELDS])
    return f"Ready to fill on Vendoo:\n{bullet}"


def write_values_into_listing(listing: dict, patches: list[dict]) -> dict:
    updated = dict(listing or {})
    for patch in patches:
        marketplace = str(patch.get("marketplace") or "general").strip().lower()
        field = str(patch.get("field") or "").strip()
        value = patch.get("value")
        if not field or value is None:
            continue
        key = normalize_field_label(field)
        if marketplace in {"", "general", "unknown"}:
            mapped = GENERAL_LISTING_KEYS.get(key)
            if not mapped:
                continue
            updated[mapped] = _coerce_listing_value(mapped, value)
            continue
        specifics_key = f"{marketplace}_specifics"
        specifics = dict(updated.get(specifics_key) or {})
        existing = next(
            (candidate for candidate in specifics if normalize_field_label(str(candidate)) == key),
            None,
        )
        specifics[existing or field] = value
        updated[specifics_key] = specifics
    return updated


def _coerce_listing_value(mapped: str, value: Any) -> Any:
    text = str(value).strip()
    if mapped in {"tags", "labels"}:
        return [part.strip() for part in text.split(",") if part.strip()]
    if mapped == "quantity":
        try:
            return int(float(text))
        except ValueError:
            return text
    if mapped in {"price", "cost"}:
        try:
            return float(text)
        except ValueError:
            return text
    return value


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
            f"not found {counts['not_found']} · invalid {counts['invalid']} · failed {counts['failed']} · "
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
                "invalid": "Invalid dropdown option",
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
        self._backfill_listing(job)
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

    def apply_field_results(self, job: Job, payload: dict | None) -> list[FillLogEntry]:
        incoming = sanitize_entries(payload)
        if not incoming:
            return []

        existing = self._repo.list_for_job(job.id)
        by_id = {entry.id: entry for entry in existing}
        used: set[str] = set()
        updated: list[FillLogEntry] = []
        for item in incoming:
            row = None
            item_id = item.get("id") or ""
            if item_id and item_id in by_id:
                row = by_id[item_id]
            if row is None:
                for candidate in existing:
                    if candidate.id in used:
                        continue
                    if candidate.marketplace == item["marketplace"] and candidate.field == item["field"]:
                        row = candidate
                        break
            if row is None:
                continue
            used.add(row.id)
            row.status = item["status"]
            row.reason = item.get("reason") or ""
            if item.get("selector"):
                row.selector = item["selector"]
            row.value_preview = item.get("value_preview") or ""
            updated.append(row)

        if not updated:
            return []

        self._db.commit()
        for row in updated:
            self._db.refresh(row)

        category_path = None
        if isinstance(job.listing_snapshot, dict):
            category_path = job.listing_snapshot.get("category_path") or None
        grouped: dict[str, list[dict]] = {}
        for row in updated:
            grouped.setdefault(row.marketplace, []).append({
                "field": row.field,
                "status": row.status,
                "selector": row.selector or "",
            })
        for marketplace, entries in grouped.items():
            self._update_registry(marketplace, category_path, entries)
        self.write_markdown(job)
        return updated

    def clear_job(self, job_id: str) -> None:
        self._repo.delete_for_job(job_id)
        path = self.log_path(job_id)
        if path.exists():
            path.unlink()

    def clear_step(self, job_id: str, step: str) -> None:
        if not step:
            return
        self._repo.delete_for_step(job_id, step)
        # Markdown is rewritten lazily on the next save; remove only when empty.
        if not self._repo.list_for_job(job_id):
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
            entry_marketplace = str(entry.get("marketplace") or marketplace or "").strip() or marketplace
            if status == "new":
                self._registry.ensure_field(
                    marketplace=entry_marketplace,
                    field_label=label,
                    selector=selector,
                    category_path=category_path,
                )
                continue
            if status in {"filled", "uncertain", "not_found", "failed"} and selector:
                self._registry.record_fill_result(
                    marketplace=entry_marketplace,
                    field_label=label,
                    selector=selector,
                    success=status == "filled",
                    category_path=category_path,
                )

    def _backfill_listing(self, job: Job) -> None:
        from copy import deepcopy

        from vendoo_studio.repositories.queries import ListingRepo
        from vendoo_studio.services.registry import RegistryService

        listing_repo = ListingRepo(self._db)
        revisions = listing_repo.get_revisions(job.conversation_id)
        if revisions:
            listing = deepcopy(revisions[0].listing_json or {})
            parent_id = revisions[0].id
        else:
            listing = deepcopy(job.listing_snapshot or {})
            parent_id = None

        snapshot = job.listing_snapshot if isinstance(job.listing_snapshot, dict) else {}
        if not listing.get("category_path") and snapshot.get("category_path"):
            listing["category_path"] = snapshot.get("category_path")

        added = RegistryService(self._db).merge_learned_fields(listing)
        if not added:
            return

        listing_repo.save_revision(
            job.conversation_id,
            listing,
            source="fill_learned_fields",
            parent_revision_id=parent_id,
        )
        self._db.commit()


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
