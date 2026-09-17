"""Category checks and readback retries after the extension saves a Vendoo draft."""

from __future__ import annotations

import asyncio
import re
from copy import deepcopy

from sqlalchemy.orm import Session

from vendoo_studio.repositories.queries import ConversationRepo, JobRepo
from vendoo_studio.services.completion_pause import (
    pause_job,
)

MAX_READBACK_RETRIES = 2
MAX_CATEGORY_REPAIRS = 1
READBACK_RETRY_DELAY_SECONDS = 2.0

AUTOMATION_TAB_STEPS = frozenset({
    "verifying_draft",
    "resolving_fields",
    "filling_fields",
    "filling_general",
    "saving_general",
    "auditing_general",
    "discovering_schema",
})


def _normalize_category_text(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = re.sub(r"[▸▶‣›*]+", " ", text)
    text = text.replace("_", " ").replace("-", " ")
    return " ".join(text.split()).casefold()


def _category_segments(value: str) -> list[str]:
    raw = str(value or "").replace("‣", ">").replace("▸", ">").replace("▶", ">").replace("›", ">")
    return [part for part in (_normalize_category_text(seg) for seg in raw.split(">")) if part]


def categories_match(observed: str, expected: str) -> bool:
    """True when the live Vendoo breadcrumb represents the selected category path.

    Mirrors extension categoryDisplayMatches: separator/CSS differences and leaf
    aliases must not pause completion when the draft already has the right category.
    """
    want = str(expected or "").strip()
    shown = str(observed or "").strip()
    if not want:
        return True
    if not shown:
        return False
    if _normalize_category_text(shown) == _normalize_category_text(want):
        return True
    segs = _category_segments(want)
    shown_parts = _category_segments(shown)
    if not segs or not shown_parts:
        return False
    want_leaf = segs[-1]
    shown_leaf = shown_parts[-1]
    shown_norm = " ".join(shown_parts)

    def hay_has(seg: str) -> bool:
        token = _normalize_category_text(seg)
        if not token:
            return False
        if shown_norm == token or token in shown_parts:
            return True
        if shown_norm.endswith(token) or shown_norm.startswith(token):
            return True
        return bool(re.search(rf"(?:^|[^a-z0-9]){re.escape(token)}(?:[^a-z0-9]|$)", shown_norm))

    tee_leaf = bool(
        re.search(r"t[\s-]?shirts?|\btees?\b", shown_leaf)
        or re.search(r"t[\s-]?shirts?\s*$", shown_norm)
        or re.search(r"tees?\s*$", shown_norm)
    )
    if re.search(r"\bblouses?\b", want_leaf):
        if tee_leaf:
            return False
        without_parent = re.sub(r"tops\s*&\s*blouses", "X", shown_norm)
        terminal_blouse = shown_leaf in {"blouse", "blouses"} or bool(
            re.search(r"(?:^|[^a-z0-9])blouses?$", without_parent)
        )
        if not terminal_blouse:
            return False
    elif want_leaf not in {shown_leaf} and not hay_has(want_leaf):
        # Singular/plural leaf aliases (Blouse vs Blouses, T-shirt vs T-shirts).
        aliases = {want_leaf, want_leaf.rstrip("s"), f"{want_leaf}s"}
        if shown_leaf not in aliases and not any(hay_has(alias) for alias in aliases):
            return False
    if len(segs) >= 2:
        parent = segs[-2]
        if hay_has(parent) or parent in shown_norm:
            return True
    return all(hay_has(seg) for seg in segs)


def schema_section_readable(section: dict | None) -> bool:
    section = section or {}
    return bool(section.get("fields")) and not section.get("error")


def incomplete_readback(verification: dict, platforms: list[str], *, vendoo_item_id: str | None) -> bool:
    """True when Chrome did not return a usable form schema for every selected marketplace."""
    schema = verification.get("schema") or {}
    if not verification.get("readback") or not vendoo_item_id:
        return True
    return any(not schema_section_readable(schema.get(mp)) for mp in platforms)


def failed_readback_platforms(verification: dict, platforms: list[str]) -> list[str]:
    schema = verification.get("schema") or {}
    return [mp for mp in platforms if not schema_section_readable(schema.get(mp))]


def merge_prior_readback_schemas(repo: JobRepo, job_id: str, verification: dict, platforms: list[str]) -> dict:
    """Keep marketplace sections that already scraped cleanly across verification attempts."""
    merged = deepcopy(verification) if isinstance(verification, dict) else {}
    schema = deepcopy(merged.get("schema") or {})
    for event in repo.get_events(job_id):
        if event.event_type != "completion_review":
            continue
        prior = (event.payload or {}).get("schema") or {}
        if not isinstance(prior, dict):
            continue
        for marketplace in platforms:
            if schema_section_readable(schema.get(marketplace)):
                continue
            previous = prior.get(marketplace)
            if schema_section_readable(previous):
                schema[marketplace] = deepcopy(previous)
    merged["schema"] = schema
    if any(schema_section_readable(schema.get(mp)) for mp in platforms):
        merged["readback"] = True
    return merged


def category_mismatches(verification: dict, listing: dict) -> list[dict]:
    """Return marketplaces whose saved category does not match the listing selection."""
    schema = verification.get("schema") or {}
    mismatches: list[dict] = []
    expected_general = str(listing.get("category_path") or "").strip()
    observed_general = str((schema.get("general", {}).get("category") or {}).get("path") or "").strip()
    if expected_general and not categories_match(observed_general, expected_general):
        mismatches.append({
            "marketplace": "general",
            "expected": expected_general,
            "observed": observed_general,
        })
    for marketplace, expected in (listing.get("marketplace_categories") or {}).items():
        want = str(expected or "").strip()
        if not want:
            continue
        observed = str((schema.get(marketplace, {}).get("category") or {}).get("path") or "").strip()
        if not categories_match(observed, want):
            mismatches.append({
                "marketplace": str(marketplace),
                "expected": want,
                "observed": observed,
            })
    return mismatches


def _category_repair_count(repo: JobRepo, job_id: str, resume_sequence: int) -> int:
    return sum(
        1
        for event in repo.get_events(job_id)
        if event.event_type == "completion_category_repair" and event.sequence > resume_sequence
    )


async def repair_category_mismatches(db: Session, job, mismatches: list[dict]) -> bool:
    """Re-apply selected categories on Vendoo, then verify again.

    Returns True when repair was dispatched (caller should stop). False means retries
    are exhausted and the job should pause.
    """
    from vendoo_studio.routes.extension import dispatch_fill_fields, extension_manager

    repo = JobRepo(db)
    events = repo.get_events(job.id)
    resume_sequence = max((e.sequence for e in events if e.event_type == "completion_resumed"), default=-1)
    attempt = _category_repair_count(repo, job.id, resume_sequence)
    if attempt >= MAX_CATEGORY_REPAIRS:
        return False
    if not extension_manager.connected:
        pause_job(db, job, "Connect Chrome to continue verifying and repairing this draft.", [])
        return True
    if any(other.id != job.id for other in repo.get_running()):
        pause_job(db, job, "Another automation job is running. Resume this draft when it finishes.", [])
        return True
    patches = [{
        "marketplace": item["marketplace"],
        "field": "Category",
        "selector": "",
        "value": item["expected"],
    } for item in mismatches if item.get("expected")]
    if not patches:
        return False
    next_attempt = attempt + 1
    detail = ", ".join(
        f"{item['marketplace']} (saved {item['observed'] or 'empty'} → {item['expected']})"
        for item in mismatches
    )
    repo.add_event(
        job.id,
        "completion_category_repair",
        "filling_fields",
        {"attempt": next_attempt, "max": MAX_CATEGORY_REPAIRS, "mismatches": mismatches},
    )
    job.status = "dispatched"
    job.current_step = "filling_fields"
    job.last_error = None
    db.commit()
    ConversationRepo(db).add_message(
        job.conversation_id,
        "system",
        f"Saved draft category differed ({detail}). "
        f"Re-applying the selected categor{'y' if len(patches) == 1 else 'ies'} "
        f"({next_attempt}/{MAX_CATEGORY_REPAIRS})…",
        provider="system",
        model="",
    )
    platforms = sorted({str(patch["marketplace"]) for patch in patches if patch["marketplace"] != "general"})
    if not await dispatch_fill_fields(job, patches, platforms=platforms or None, reload=False):
        pause_job(db, job, "Chrome disconnected before the category could be re-applied.", [])
    return True


def _readback_retry_count(repo: JobRepo, job_id: str, resume_sequence: int) -> int:
    return sum(
        1
        for event in repo.get_events(job_id)
        if event.event_type == "completion_readback_retry" and event.sequence > resume_sequence
    )


def _readback_detail(verification: dict, platforms: list[str]) -> str:
    schema = verification.get("schema") or {}
    details = []
    for mp in platforms:
        section = schema.get(mp) or {}
        err = section.get("error")
        fields = section.get("fields") or []
        if err:
            details.append(f"{mp}: {err}")
        elif not fields:
            details.append(f"{mp}: no fields")
    return "; ".join(details) if details else "incomplete readback"


async def retry_incomplete_readback(
    db: Session,
    job,
    platforms: list[str],
    verification: dict,
    *,
    failed: list[str],
) -> bool:
    """Re-dispatch draft verification for marketplaces that still lack a readable schema.

    Returns True when a retry was scheduled (caller should stop). False means retries
    are exhausted and the job should pause for review.
    """
    from vendoo_studio.routes.extension import dispatch_fill_fields, extension_manager

    repo = JobRepo(db)
    events = repo.get_events(job.id)
    resume_sequence = max((e.sequence for e in events if e.event_type == "completion_resumed"), default=-1)
    attempt = _readback_retry_count(repo, job.id, resume_sequence)
    detail = _readback_detail(verification, failed or platforms)
    if attempt >= MAX_READBACK_RETRIES:
        return False
    if not extension_manager.connected:
        pause_job(db, job, "Connect Chrome to continue verifying and repairing this draft.", [])
        return True
    if any(other.id != job.id for other in repo.get_running()):
        pause_job(db, job, "Another automation job is running. Resume this draft when it finishes.", [])
        return True
    next_attempt = attempt + 1
    # Prefer re-reading only the failed marketplaces; always include general when it failed.
    retry_platforms = [mp for mp in (failed or platforms) if mp != "general"]
    include_general = "general" in (failed or platforms) or not failed
    verify_platforms = (["general"] if include_general else []) + retry_platforms
    if not verify_platforms:
        verify_platforms = list(platforms)
    repo.add_event(
        job.id,
        "completion_readback_retry",
        "verifying_draft",
        {
            "attempt": next_attempt,
            "max": MAX_READBACK_RETRIES,
            "detail": detail,
            "platforms": verify_platforms,
        },
    )
    job.status = "dispatched"
    job.current_step = "verifying_draft"
    job.last_error = None
    db.commit()
    ConversationRepo(db).add_message(
        job.conversation_id,
        "system",
        f"Marketplace forms were not fully readable ({detail}). "
        f"Retrying verification for {', '.join(verify_platforms)} "
        f"({next_attempt}/{MAX_READBACK_RETRIES})…",
        provider="system",
        model="",
    )
    delay = READBACK_RETRY_DELAY_SECONDS * next_attempt
    await asyncio.sleep(delay)
    db.refresh(job)
    if job.status == "cancelled":
        return True
    if not await dispatch_fill_fields(
        job,
        [],
        platforms=verify_platforms,
        reload=False,
    ):
        pause_job(db, job, "Chrome disconnected before verification could be retried.", [])
    return True
