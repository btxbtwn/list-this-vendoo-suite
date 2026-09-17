"""Fill fields the seller pointed at in the interactive Vendoo browser.

The seller picks or circles fields on the live draft and writes a note. The
listing provider resolves values for exactly those fields, Studio saves them to
the listing JSON, and the extension types them into the draft. Nothing is
published.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services.fill_log import (
    MAX_PATCH_VALUE,
    FillLogService,
    extract_missing_fields,
    field_lookup_key,
    normalize_field_label,
    repair_missing_fields,
    write_values_into_listing,
)
from vendoo_studio.services.listing_field_gaps import GAP_FILL_SYSTEM
from vendoo_studio.services.registry import SELLER_SETTING_LABELS, is_account_managed_field

log = logging.getLogger(__name__)

MAX_DIRECT_FIELDS = 30
MAX_OPTIONS = 40
MARKETPLACES = frozenset({"general", "ebay", "etsy", "poshmark", "mercari", "depop"})
MARKET_LABELS = {
    "general": "Vendoo",
    "ebay": "eBay",
    "etsy": "Etsy",
    "poshmark": "Poshmark",
    "mercari": "Mercari",
    "depop": "Depop",
}

DIRECT_FILL_SYSTEM = (
    GAP_FILL_SYSTEM
    + "\n- The seller pointed at these fields on the live Vendoo draft. Their note outranks photo inference."
    + "\n- Replace a current value when the note or the evidence shows it is wrong."
)

_background: set[asyncio.Task] = set()


def split_targets(targets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Dedupe picked fields and set aside account-level settings Studio never fills."""
    fillable: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in targets:
        marketplace = str(raw.get("marketplace") or "general").strip().lower()
        field = str(raw.get("field") or "").strip()
        if marketplace not in MARKETPLACES or not field:
            continue
        key = (marketplace, normalize_field_label(field))
        if key in seen:
            continue
        seen.add(key)
        if (
            raw.get("account_managed")
            or field_lookup_key(field) in SELLER_SETTING_LABELS
            or is_account_managed_field(marketplace, field)
        ):
            skipped.append({"marketplace": marketplace, "field": field, "reason": "account setting"})
            continue
        options = [str(option).strip() for option in raw.get("options") or [] if str(option).strip()]
        fillable.append({
            "marketplace": marketplace,
            "field": field,
            "current": str(raw.get("value") or "").strip(),
            "selector": str(raw.get("selector") or "").strip(),
            "options": options[:MAX_OPTIONS],
        })
    return fillable[:MAX_DIRECT_FIELDS], skipped


def build_direct_request(listing: dict, targets: list[dict[str, Any]], note: str) -> str:
    title = str(listing.get("title") or "Untitled").strip() or "Untitled"
    lines: list[str] = []
    for target in targets:
        line = (
            f"- Marketplace: {target['marketplace']}\n"
            f"  Field: {target['field']}\n"
            f"  Value on Vendoo now: {target['current'] or '(empty)'}"
        )
        if target["options"]:
            line += f"\n  Allowed options: {', '.join(target['options'])}"
        lines.append(line)
    seller_note = note.strip() or "(no note) Fill these fields from the photos and listing."
    return (
        f'The seller pointed at these fields on the Vendoo draft for "{title}".\n\n'
        f"Seller note: {seller_note}\n\n"
        "Return values for ONLY these fields. Use the marketplace ids and field names exactly as listed.\n\n"
        "Reply with JSON in this exact shape:\n\n"
        '```json\n{"missing_fields":[{"marketplace":"general","field":"SKU","value":"..."}]}\n```\n\n'
        "Fields:\n" + "\n".join(lines)
    )


def _latest_listing(db: Session, job) -> dict:
    revisions = ListingRepo(db).get_revisions(job.conversation_id)
    if revisions and isinstance(revisions[0].listing_json, dict):
        return dict(revisions[0].listing_json)
    snapshot = job.listing_snapshot if isinstance(job.listing_snapshot, dict) else {}
    return {key: value for key, value in snapshot.items() if key != "platforms"}


def _patch_value(value: Any) -> str:
    if isinstance(value, list):
        value = ", ".join(str(part).strip() for part in value if str(part).strip())
    return str(value).strip()[:MAX_PATCH_VALUE]


def restrict_patches(patches: list[dict] | None, targets: list[dict[str, Any]]) -> list[dict[str, str]]:
    by_key = {(t["marketplace"], normalize_field_label(t["field"])): t for t in targets}
    result: list[dict[str, str]] = []
    for patch in patches or []:
        marketplace = str(patch.get("marketplace") or "general").strip().lower()
        target = by_key.pop((marketplace, normalize_field_label(str(patch.get("field") or ""))), None)
        if target is None:
            continue
        value = _patch_value(patch.get("value"))
        if not value or value == target["current"]:
            continue
        result.append({
            "marketplace": marketplace,
            "field": target["field"],
            "value": value,
            "selector": target["selector"],
        })
    return result


async def plan_values(db: Session, job, provider, targets: list[dict[str, Any]], note: str) -> list[dict[str, str]]:
    from vendoo_studio.services.listing_generate import collect_provider_text, latest_photo_analysis

    listing = _latest_listing(db, job)
    evidence = latest_photo_analysis(ConversationRepo(db).get_messages(job.conversation_id)) or "(no photo analysis)"
    request = build_direct_request(listing, targets, note)
    messages = [
        {"role": "system", "content": DIRECT_FILL_SYSTEM},
        {
            "role": "user",
            "content": (
                f"{request}\n\n--- Evidence ---\n{evidence}\n\n"
                f"--- Current listing ---\n{json.dumps(listing, ensure_ascii=False)}"
            ),
        },
    ]
    text = await collect_provider_text(provider, messages)
    patches = extract_missing_fields(text) or await repair_missing_fields(provider, text, request)
    return restrict_patches(patches, targets)


def describe_request(targets: list[dict[str, Any]], skipped: list[dict[str, Any]], note: str) -> str:
    names = [f"{MARKET_LABELS.get(t['marketplace'], t['marketplace'])} / {t['field']}" for t in [*targets, *skipped]]
    head = note.strip() or "Fill these fields."
    return f"{head}\n\nFields I pointed at in the Vendoo browser: {', '.join(names)}"


def describe_values(patches: list[dict[str, str]]) -> str:
    lines = [f"- {MARKET_LABELS.get(p['marketplace'], p['marketplace'])} / {p['field']}: {p['value'][:120]}" for p in patches]
    return "Typing these values into the Vendoo draft:\n" + "\n".join(lines)


async def direct_fill(db: Session, job, provider, raw_targets: list[dict[str, Any]], note: str) -> dict[str, Any]:
    """Resolve values for picked fields, save them, and start typing them into Vendoo."""
    repo = ConversationRepo(db)
    targets, skipped = split_targets(raw_targets)
    repo.add_message(job.conversation_id, "user", describe_request(targets, skipped, note))
    if skipped:
        repo.add_message(
            job.conversation_id,
            "system",
            "Skipped account-level settings you manage in each marketplace: "
            + ", ".join(f"{MARKET_LABELS.get(s['marketplace'], s['marketplace'])} / {s['field']}" for s in skipped),
            provider="system",
            model="",
        )
    if not targets:
        return {"ok": False, "patches": [], "skipped": skipped, "error": "None of those fields can be filled by Studio."}

    patches = await plan_values(db, job, provider, targets, note)
    if not patches:
        repo.add_message(
            job.conversation_id,
            "system",
            "The listing assistant had no new values for those fields. Add a note with the value you want.",
            provider="system",
            model="",
        )
        return {"ok": False, "patches": [], "skipped": skipped, "error": "No new values for those fields."}

    listing = _latest_listing(db, job)
    updated = write_values_into_listing(listing, patches)
    listing_repo = ListingRepo(db)
    revisions = listing_repo.get_revisions(job.conversation_id)
    listing_repo.save_revision(
        job.conversation_id,
        updated,
        source="browser_direct",
        parent_revision_id=revisions[0].id if revisions else None,
    )
    FillLogService(db).record_generated_values(job.conversation_id, patches)
    repo.add_message(job.conversation_id, "system", describe_values(patches), provider="system", model="")

    task = asyncio.create_task(_apply_in_background(job.id, updated, patches))
    _background.add(task)
    task.add_done_callback(_background.discard)
    return {"ok": True, "patches": patches, "skipped": skipped}


async def _apply_in_background(job_id: str, listing: dict, patches: list[dict[str, str]]) -> None:
    from vendoo_studio.database import SessionLocal
    from vendoo_studio.repositories.queries import JobRepo
    from vendoo_studio.services.auto_apply import apply_patches

    db = SessionLocal()
    try:
        job = JobRepo(db).get(job_id)
        if job is None:
            return
        ok, error = await apply_patches(db, job, listing, patches)
        if not ok:
            ConversationRepo(db).add_message(
                job.conversation_id,
                "system",
                f"Could not type those values into Vendoo: {error or 'unknown error'}. They are saved in the listing.",
                provider="system",
                model="",
            )
    except Exception:
        log.exception("browser direct fill failed for job %s", job_id)
    finally:
        db.close()
