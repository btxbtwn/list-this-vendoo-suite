"""Decide which marketplace forms Send can skip because the saved draft already matches."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from vendoo_studio.repositories.queries import JobRepo


def _normalize(value: Any) -> Any:
    if isinstance(value, list):
        return frozenset(_normalize(item) for item in value if str(item).strip())
    if isinstance(value, bool):
        return str(value).casefold()
    if isinstance(value, (int, float)):
        return float(value)
    text = " ".join(str(value).split()).casefold()
    try:
        return float(text)
    except ValueError:
        return text


def _flatten(record: dict, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in record.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            out.update(_flatten(value, path))
        elif value not in (None, "", []):
            out[path] = value
    return out


def specifics_match(expected: dict | None, observed: dict | None) -> bool:
    """Every non-empty listing value is present in the draft with the same value."""
    wanted = _flatten(expected) if isinstance(expected, dict) else {}
    have = _flatten(observed) if isinstance(observed, dict) else {}
    if not wanted or not have:
        return False
    return all(key in have and _normalize(have[key]) == _normalize(value) for key, value in wanted.items())


def latest_draft_item(db: Session, conversation_id: str, item_id: str) -> dict | None:
    repo = JobRepo(db)
    best = None
    for job in repo.list_by_conversation(conversation_id):
        event = repo.latest_event(job.id, "vendoo_draft")
        payload = event.payload if event is not None and isinstance(event.payload, dict) else None
        if not payload or not isinstance(payload.get("item"), dict):
            continue
        if str(payload.get("item_id") or job.vendoo_item_id or "") != str(item_id):
            continue
        if best is None or (event.created_at and best[0] and event.created_at > best[0]):
            best = (event.created_at, payload["item"])
    return best[1] if best else None


def matching_marketplaces(
    db: Session,
    conversation_id: str,
    item_id: str | None,
    listing: dict,
    platforms: list[str],
) -> list[str]:
    """Marketplaces whose saved Vendoo specifics already equal the listing's.

    End-of-job verification still reads every marketplace back, so a stale cache only
    costs a completion repair round, never a silently wrong draft.
    """
    if not item_id or not isinstance(listing, dict) or not platforms:
        return []
    item = latest_draft_item(db, conversation_id, item_id)
    if not item:
        return []
    from vendoo_studio.services.vendoo_import import listing_from_vendoo

    observed = listing_from_vendoo(item, None)
    return [
        marketplace
        for marketplace in platforms
        if specifics_match(listing.get(f"{marketplace}_specifics"), observed.get(f"{marketplace}_specifics"))
    ]
