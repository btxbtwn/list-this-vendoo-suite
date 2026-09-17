"""Apply generated listing values onto the bound Vendoo draft without a manual click."""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services.fill_log import (
    FILLABLE_STATUSES,
    MAX_FILL_FIELDS,
    MAX_PATCH_FIELDS,
    FillLogService,
    canonical_option,
    field_lookup_key,
    listing_value_for_field,
    normalize_field_label,
    write_values_into_listing,
)
from vendoo_studio.services.registry import SELLER_SETTING_LABELS, is_account_managed_field

log = logging.getLogger(__name__)

SKIP_KEYS = frozenset({
    "itemid", "userid", "datecreated", "datelastmodified", "datelisted", "lastdatelisted",
    "laststatusdate", "listings", "images", "videos", "id", "errors", "error", "extras",
    "siteid", "enabled", "listed", "listedid", "listingid", "listingurl", "listingattemptmessages",
    "marketplaceaccount", "marketplaceid", "sales", "status", "origin", "version", "validate",
    "hash", "draftid", "lastsynced", "lastmodified", "statuses", "fieldlabels", "categoryv2",
})
UNFILLABLE_FIELDS = frozenset({"photos", "images", "videos", "image"})
MARKETPLACE_ORDER = ("general", "ebay", "etsy", "poshmark", "mercari", "depop")
FILL_WAIT_TIMEOUT_SEC = 600.0
# Fill statuses where Vendoo did not accept the typed value as one of its options.
REJECTED_FILL_STATUSES = frozenset({"invalid", "uncertain"})


def _field_label(key: str) -> str:
    leaf = key.split(".")[-1]
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", leaf)
    spaced = spaced.replace("_", " ").strip()
    return spaced[:1].upper() + spaced[1:] if spaced else leaf


def _is_empty(value: Any) -> bool:
    if value is None or value == "" or value == []:
        return True
    if isinstance(value, dict):
        if value.get("displayName"):
            return False
        if "value" in value and len(value) <= 3:
            return _is_empty(value.get("value"))
        if not value:
            return True
        return all(_is_empty(item) for item in value.values())
    return False


def _display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(part).strip() for part in value if str(part).strip())
    if isinstance(value, dict):
        if isinstance(value.get("displayName"), str):
            return value["displayName"].strip()
        if value.get("value") is not None and len(value) <= 3:
            return _display_value(value.get("value"))
        if value.get("option") is not None:
            return _display_value(value.get("option"))
    return str(value).strip()


def _flatten_vendoo_fields(
    value: Any,
    *,
    prefix: str = "",
    labels: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if value is None or not isinstance(value, dict) or isinstance(value, list):
        if not prefix:
            return []
        label = (labels or {}).get(prefix) or (labels or {}).get(prefix.split(".")[-1]) or _field_label(prefix)
        shown = _display_value(value)
        return [{
            "label": label,
            "value": shown,
            "missing": _is_empty(value),
        }]

    record = value
    if (
        isinstance(record.get("displayName"), str)
        or isinstance(record.get("displayPath"), list)
        or record.get("option") is not None
        or ("value" in record and len(record) <= 3)
    ):
        label = (labels or {}).get(prefix) or (labels or {}).get(prefix.split(".")[-1]) or _field_label(prefix or "value")
        shown = _display_value(record)
        return [{
            "label": label,
            "value": shown,
            "missing": _is_empty(record),
        }]

    rows: list[dict[str, Any]] = []
    for key, nested in record.items():
        if str(key).lower() in SKIP_KEYS:
            continue
        if key == "category" and record.get("categoryV2"):
            continue
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(nested, dict) and not isinstance(nested, list):
            nested_record = nested
            if nested_record.get("option") is not None and nested_record.get("scale") is not None:
                rows.append({
                    "label": "US Size",
                    "value": _display_value(nested_record.get("option")),
                    "missing": _is_empty(nested_record.get("option")),
                })
                rows.append({
                    "label": "Size Type",
                    "value": _display_value(nested_record.get("scale")),
                    "missing": _is_empty(nested_record.get("scale")),
                })
                continue
            leaf = (
                isinstance(nested_record.get("displayName"), str)
                or isinstance(nested_record.get("displayPath"), list)
                or nested_record.get("option") is not None
                or ("value" in nested_record and len(nested_record) <= 3)
            )
            if not leaf and not _is_empty(nested) and len(nested_record) > 1:
                rows.extend(_flatten_vendoo_fields(nested, prefix=path, labels=labels))
                continue
        label = (labels or {}).get(path) or (labels or {}).get(str(key)) or _field_label(str(key))
        shown = _display_value(nested)
        rows.append({
            "label": label,
            "value": shown,
            "missing": _is_empty(nested),
        })
    return rows


def _listing_section(listing: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(listing, dict):
        return {}
    rest = dict(listing)
    overrides = rest.pop("overrides", None)
    specifics = rest.pop("marketplaceSpecifics", None)
    category = rest.pop("categorySpecifics", None)
    rest.pop("fieldLabels", None)
    rest.pop("type", None)
    merged = dict(rest)
    if isinstance(overrides, dict):
        merged.update(overrides)
    if isinstance(specifics, dict):
        merged.update(specifics)
    if isinstance(category, dict):
        merged.update(category)
    return merged


def _field_labels(listing: dict[str, Any] | None) -> dict[str, str]:
    raw = listing.get("fieldLabels") if isinstance(listing, dict) else None
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for path, label in raw.items():
        if not isinstance(label, str) or not label.strip():
            continue
        text = label.strip()
        out[str(path)] = text
        bare = ".".join(str(path).split(".")[1:])
        if bare:
            out[bare] = text
    return out


def _should_skip_field(marketplace: str, label: str) -> bool:
    key = field_lookup_key(label)
    if key in UNFILLABLE_FIELDS:
        return True
    if key in SELLER_SETTING_LABELS:
        return True
    return is_account_managed_field(marketplace, label)


def _selector_map(report: dict) -> dict[tuple[str, str], str]:
    selectors: dict[tuple[str, str], str] = {}
    for marketplace, group in (report.get("by_marketplace") or {}).items():
        for entry in group.get("entries") or []:
            field = str(entry.get("field") or "").strip()
            selector = str(entry.get("selector") or "").strip()
            if not field or not selector:
                continue
            selectors[(str(marketplace).lower(), normalize_field_label(field))] = selector
    return selectors


def registry_option_lookup(db: Session, category_path: str | None):
    """Known dropdown options per (marketplace, field) from the learned registry."""
    from vendoo_studio.repositories.queries import RegistryRepo

    repo = RegistryRepo(db)

    def lookup(marketplace: str, field: str) -> list[str]:
        try:
            return repo.get_valid_options(marketplace, field, category_path or None)
        except Exception:
            log.exception("registry option lookup failed for %s/%s", marketplace, field)
            return []

    return lookup


def build_apply_patches(
    listing: dict,
    item: dict | None,
    report: dict,
    options_for=None,
) -> list[dict[str, str]]:
    """Build fill patches for empty Vendoo fields that already have listing values.

    options_for(marketplace, field) returns known dropdown labels; matching values are
    rewritten to the exact label so Chrome clicks an option instead of typing a fallback.
    """
    if not isinstance(item, dict):
        return []

    selectors = _selector_map(report)
    patches: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add_patch(marketplace: str, label: str) -> None:
        if _should_skip_field(marketplace, label):
            return
        lookup = normalize_field_label(label)
        key = (marketplace, lookup)
        if key in seen:
            return
        value = listing_value_for_field(listing, marketplace, label)
        if not value:
            return
        if options_for is not None:
            value = canonical_option(value, options_for(marketplace, label)) or value
        seen.add(key)
        patch = {
            "marketplace": marketplace,
            "field": label,
            "value": value,
            "selector": selectors.get(key, ""),
        }
        patches.append(patch)

    general = item.get("generalDetails")
    if isinstance(general, dict):
        for field in _flatten_vendoo_fields(general):
            if not field.get("missing"):
                continue
            add_patch("general", str(field["label"]))

    listings = item.get("listings") if isinstance(item.get("listings"), dict) else {}
    statuses = item.get("statuses") if isinstance(item.get("statuses"), dict) else {}
    marketplace_ids = [
        *[
            mp for mp in MARKETPLACE_ORDER
            if mp != "general" and (mp in listings or mp in statuses)
        ],
        *[
            mp for mp in listings
            if mp not in MARKETPLACE_ORDER and mp != "general"
        ],
    ]
    for marketplace in marketplace_ids:
        listing_blob = listings.get(marketplace) if isinstance(listings.get(marketplace), dict) else {}
        section = _listing_section(listing_blob)
        labels = _field_labels(listing_blob)
        for field in _flatten_vendoo_fields(section, labels=labels):
            if not field.get("missing"):
                continue
            add_patch(marketplace, str(field["label"]))

    return patches[:MAX_FILL_FIELDS]


def find_apply_job(db: Session, conv_id: str):
    from vendoo_studio.services.schema_probe import is_schema_probe_job

    job_repo = JobRepo(db)
    candidates = job_repo.list_by_conversation(conv_id)
    for job in candidates:
        if not job.vendoo_item_id or str(job.vendoo_item_id).lower() in {"new", "edit", "create"}:
            continue
        if job.status in {"cancelled"}:
            continue
        if is_schema_probe_job(job) or job.status in {"completed", "failed"}:
            return job
    return None


async def _read_live_draft(db: Session, job) -> dict | None:
    from vendoo_studio.routes.extension import (
        VENDOO_GET_TIMEOUT_SEC,
        dispatch_vendoo_get,
        extension_manager,
    )

    if not extension_manager.connected:
        return None

    request_id = uuid.uuid4().hex[:12]
    waiter = extension_manager.register_wait(request_id)
    try:
        sent = await dispatch_vendoo_get(job, request_id, api_only=True)
        if not sent:
            return None
        payload = await asyncio.wait_for(waiter, timeout=VENDOO_GET_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        log.warning("auto apply draft read timed out for job %s", job.id)
        return None
    finally:
        extension_manager.cancel_wait(request_id)

    if not payload.get("ok"):
        return None

    item = payload.get("item") if isinstance(payload.get("item"), dict) else None
    JobRepo(db).save_vendoo_draft(
        job.id,
        item=item,
        form=payload.get("form") if isinstance(payload.get("form"), dict) else None,
        item_id=payload.get("item_id") or job.vendoo_item_id,
        url=payload.get("url") or job.vendoo_url,
        source=payload.get("source") or "live",
        step=job.current_step,
        statuses=payload.get("statuses") if isinstance(payload.get("statuses"), dict) else None,
    )
    return item


async def _wait_for_fill(job_id: str, db_factory) -> tuple[bool, str | None]:
    deadline = asyncio.get_running_loop().time() + FILL_WAIT_TIMEOUT_SEC
    while asyncio.get_running_loop().time() < deadline:
        db = db_factory()
        try:
            job = JobRepo(db).get(job_id)
            if not job:
                return False, "Job not found"
            if job.status == "completed" and job.current_step == "fields_applied":
                return True, None
            if job.status == "failed":
                return False, job.last_error or "Apply on Vendoo failed"
        finally:
            db.close()
        await asyncio.sleep(0.75)
    return False, "Timed out waiting for Vendoo to finish applying values"


async def apply_patches(db: Session, job, listing: dict, patches: list[dict]) -> tuple[bool, str | None]:
    from vendoo_studio.routes.extension import dispatch_fill_fields, extension_manager
    from vendoo_studio.database import SessionLocal

    if not patches:
        return True, None
    if not extension_manager.connected:
        return False, "Chrome is not connected"
    active = [item for item in JobRepo(db).get_active() if item.id != job.id]
    if active:
        return False, "Another automation job is already running"

    platforms = (job.listing_snapshot or {}).get("platforms") or []
    job.listing_snapshot = {**listing, "platforms": platforms}
    job.status = "dispatched"
    job.current_step = "filling_fields"
    job.last_error = None
    db.commit()
    JobRepo(db).add_event(
        job.id,
        "auto_apply",
        "filling_fields",
        {"count": len(patches), "patches": patches[:20]},
    )

    sent = await dispatch_fill_fields(job, patches, verify=False, read_item=True)
    if not sent:
        job.status = "failed"
        job.current_step = "filling_fields"
        job.last_error = "Could not reach the Chrome extension"
        db.commit()
        return False, job.last_error

    ok, error = await _wait_for_fill(job.id, SessionLocal)
    db.refresh(job)
    if ok:
        ConversationRepo(db).add_message(
            job.conversation_id,
            "system",
            f"Applied {len(patches)} generated value(s) onto the Vendoo draft. Review Fields, then Send when ready.",
            provider="system",
            model="",
        )
    return ok, error


def rejected_fill_gaps(db: Session, job, patches: list[dict], options_for) -> list[dict]:
    """Patched fields Vendoo rejected in the latest apply, with the options offered for them."""
    event = JobRepo(db).latest_event(job.id, "step_completed")
    payload = event.payload if event is not None and isinstance(event.payload, dict) else {}
    if event is None or event.step != "filling_fields":
        return []
    fill_log = payload.get("fill_log") if isinstance(payload.get("fill_log"), dict) else {}
    patched = {
        (str(patch.get("marketplace") or "general").lower(), normalize_field_label(str(patch.get("field") or "")))
        for patch in patches
    }
    gaps: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for entry in fill_log.get("entries") or []:
        if not isinstance(entry, dict) or entry.get("status") not in REJECTED_FILL_STATUSES:
            continue
        marketplace = str(entry.get("marketplace") or "general").lower()
        field = str(entry.get("field") or "").strip()
        key = (marketplace, normalize_field_label(field))
        if not field or key not in patched or key in seen:
            continue
        live = [str(option).strip() for option in entry.get("options") or [] if str(option).strip()]
        options = live or options_for(marketplace, field)
        if not options:
            continue
        seen.add(key)
        gaps.append({
            "marketplace": marketplace,
            "field": field,
            "options": options,
            "rejected": str(entry.get("value_preview") or ""),
        })
    return gaps


async def repair_rejected_fills(
    db: Session,
    job,
    listing: dict,
    patches: list[dict],
    provider,
    *,
    evidence: str,
    options_for,
) -> dict[str, Any]:
    """One automatic round: re-ask the model for rejected dropdown values and apply them."""
    from vendoo_studio.services.listing_field_gaps import _request_missing_field_values

    gaps = rejected_fill_gaps(db, job, patches, options_for)
    if not gaps or provider is None:
        return {"repaired": 0}
    responses = await _request_missing_field_values(
        provider,
        listing=listing,
        gaps=gaps,
        evidence=evidence,
    ) or []
    by_key = {(gap["marketplace"], normalize_field_label(gap["field"])): gap for gap in gaps}
    repairs: list[dict] = []
    for row in responses[:MAX_PATCH_FIELDS]:
        marketplace = str(row.get("marketplace") or "general").lower()
        gap = by_key.get((marketplace, normalize_field_label(str(row.get("field") or ""))))
        value = canonical_option(row.get("value"), gap["options"]) if gap else None
        if not gap or not value or value.casefold() == gap["rejected"].casefold():
            continue
        repairs.append({"marketplace": marketplace, "field": gap["field"], "value": value, "selector": ""})
    if not repairs:
        return {"repaired": 0, "rejected": len(gaps)}

    updated = write_values_into_listing(listing, repairs)
    listing_repo = ListingRepo(db)
    revisions = listing_repo.get_revisions(job.conversation_id)
    listing_repo.save_revision(
        job.conversation_id,
        updated,
        source="apply_repair",
        parent_revision_id=revisions[0].id if revisions else None,
    )
    ok, error = await apply_patches(db, job, updated, repairs)
    return {"repaired": len(repairs) if ok else 0, "rejected": len(gaps), "error": error}


async def auto_apply_after_generation(
    db: Session,
    conv_id: str,
    listing: dict,
    *,
    provider=None,
    evidence: str = "",
) -> dict[str, Any]:
    """Best-effort: type generated listing values onto the bound Vendoo draft."""
    from vendoo_studio.routes.extension import extension_manager

    if not isinstance(listing, dict) or not listing:
        return {"applied": False, "reason": "no_listing"}

    job = find_apply_job(db, conv_id)
    if not job:
        return {"applied": False, "reason": "no_draft_job"}

    if not extension_manager.connected:
        return {"applied": False, "reason": "chrome_disconnected", "job_id": job.id}

    item = await _read_live_draft(db, job)
    if not item:
        cached = JobRepo(db).get_vendoo_draft(job.id)
        item = cached.get("item") if isinstance(cached, dict) and isinstance(cached.get("item"), dict) else None
    if not item:
        return {"applied": False, "reason": "draft_unavailable", "job_id": job.id}

    report = FillLogService(db).report_for_job(job)
    options_for = registry_option_lookup(db, str(listing.get("category_path") or ""))
    patches = build_apply_patches(listing, item, report, options_for)
    if not patches:
        return {"applied": False, "reason": "nothing_to_apply", "job_id": job.id, "count": 0}

    ok, error = await apply_patches(db, job, listing, patches)
    result: dict[str, Any] = {
        "applied": ok,
        "job_id": job.id,
        "count": len(patches),
        "error": error,
    }
    if ok and provider is not None:
        try:
            repair = await repair_rejected_fills(
                db, job, listing, patches, provider, evidence=evidence, options_for=options_for,
            )
        except Exception:
            log.exception("automatic repair of rejected fills failed for %s", conv_id)
            repair = {"repaired": 0, "error": "repair failed"}
        result["repair"] = repair
    return result
