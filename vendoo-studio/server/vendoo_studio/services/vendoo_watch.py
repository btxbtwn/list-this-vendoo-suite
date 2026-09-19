"""Keep a bound listing in step with its Vendoo draft.

Vendoo stamps every item with ``dateLastModified``, so noticing a change there
is a matter of comparing it against what Studio last saw. What to do about it
is the harder half: pulling unconditionally would throw away edits made in
Studio, so a pull only happens when Studio has nothing of its own outstanding.
When both sides moved, neither wins automatically — the conversation is
reported as conflicted and left to the seller.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo

log = logging.getLogger("vendoo_studio.vendoo_watch")

SYNCED_AT = "vendooSyncedAt"
SYNCED_REVISION = "vendooSyncedRevision"

__all__ = [
    "sync_state",
    "apply_pull",
    "studio_has_unpushed_edits",
    "cache_pulled_item",
    "SYNCED_AT",
    "SYNCED_REVISION",
]


def _stamp(value: Any) -> int:
    """Vendoo's dateLastModified as epoch milliseconds."""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, dict) and "_seconds" in value:
        return int(value["_seconds"]) * 1000
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def studio_has_unpushed_edits(db: Session, conv_id: str) -> bool:
    """True when Studio's current revision is ahead of the last synced one."""
    from vendoo_studio.services.vendoo_import import parse_notes

    conv = ConversationRepo(db).get(conv_id)
    notes = parse_notes(conv.notes if conv else None)
    revisions = ListingRepo(db).get_revisions(conv_id)
    local_revision = revisions[0].id if revisions else None
    synced_revision = str(notes.get(SYNCED_REVISION) or "")
    return bool(local_revision and synced_revision and local_revision != synced_revision)


def sync_state(db: Session, conv_id: str, item: dict[str, Any]) -> dict[str, Any]:
    """What, if anything, should happen for this conversation.

    ``action`` is one of ``pull`` (Vendoo moved, Studio did not), ``conflict``
    (both moved), or ``none``.
    """
    # parse_notes, not vendoo_binding: the binding helper only reports the item
    # id and url, and these markers live beside them.
    from vendoo_studio.services.vendoo_import import parse_notes

    conv = ConversationRepo(db).get(conv_id)
    notes = parse_notes(conv.notes if conv else None)
    seen = _stamp(notes.get(SYNCED_AT))
    remote = _stamp((item or {}).get("dateLastModified"))

    revisions = ListingRepo(db).get_revisions(conv_id)
    local_revision = revisions[0].id if revisions else None
    local_moved = studio_has_unpushed_edits(db, conv_id)
    remote_moved = bool(remote and seen and remote > seen)

    # Nothing recorded yet: adopt Vendoo's state rather than guessing that
    # either side is ahead.
    if not seen:
        return {"action": "pull", "reason": "first sync", "remote": remote, "revision": local_revision}
    if remote_moved and local_moved:
        return {"action": "conflict", "reason": "both changed", "remote": remote, "revision": local_revision}
    if remote_moved:
        return {"action": "pull", "reason": "vendoo changed", "remote": remote, "revision": local_revision}
    return {"action": "none", "reason": "up to date", "remote": remote, "revision": local_revision}


def cache_pulled_item(
    db: Session,
    conv_id: str,
    item: dict[str, Any],
    *,
    source: str = "vendoo_pull",
) -> None:
    """Refresh the job draft cache so thread marketplace status matches Vendoo.

    The sidebar hover reads ``vendoo_draft`` via the job's cache-only path. Pull
    already fetches a fresh item; without writing it here, invalidate still
    serves the stale cache and LISTED / NOT LISTED chips stay wrong.
    """
    from vendoo_studio.services.vendoo_import import vendoo_binding

    repo = JobRepo(db)
    # The sidebar reads the newest non-cancelled job bound to Vendoo, which is
    # not always the newest job; refresh every live job so none keeps a stale draft.
    jobs = [job for job in repo.list_by_conversation(conv_id) if job.status != "cancelled"]
    if not jobs:
        return
    conv = ConversationRepo(db).get(conv_id)
    binding = vendoo_binding(conv.notes if conv else None)
    for job in jobs:
        item_id = str(
            (item or {}).get("itemID")
            or (item or {}).get("itemId")
            or binding.get("vendooItemId")
            or job.vendoo_item_id
            or ""
        ).strip()
        url = binding.get("vendooUrl") or job.vendoo_url
        repo.save_vendoo_draft(
            job.id,
            item=item,
            item_id=item_id or None,
            url=url,
            source=source,
        )


def apply_pull(
    db: Session,
    conv_id: str,
    item: dict[str, Any],
    *,
    source: str = "vendoo_sync",
) -> str | None:
    """Save Vendoo's version as a revision and record that we are in step."""
    from vendoo_studio.services.vendoo_import import listing_from_vendoo

    listing_repo = ListingRepo(db)
    revisions = listing_repo.get_revisions(conv_id)
    revision = listing_repo.save_revision(
        conv_id,
        listing_from_vendoo(item, None),
        source=source,
        parent_revision_id=revisions[0].id if revisions else None,
    )
    cache_pulled_item(db, conv_id, item, source=source)
    mark_synced(db, conv_id, item, revision.id)
    return revision.id


def mark_synced(db: Session, conv_id: str, item: dict[str, Any], revision_id: str | None) -> None:
    """Record the Vendoo stamp and revision this conversation is level with."""
    from vendoo_studio.services.vendoo_import import merge_notes

    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        return
    stamp = _stamp((item or {}).get("dateLastModified")) or int(
        datetime.now(UTC).timestamp() * 1000
    )
    conv.notes = merge_notes(conv.notes, {
        SYNCED_AT: str(stamp),
        SYNCED_REVISION: str(revision_id or ""),
    })
    db.commit()
