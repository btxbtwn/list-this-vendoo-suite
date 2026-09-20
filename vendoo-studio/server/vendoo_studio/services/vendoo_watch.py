"""Keep a bound listing in step with its Vendoo draft.

Vendoo stamps every item with ``dateLastModified``, so noticing a change there
is a matter of comparing it against what Studio last saw. What to do about it
is the harder half: pulling unconditionally would throw away edits made in
Studio, so a pull only happens when Studio has nothing of its own outstanding.
When both sides moved, neither wins automatically — the conversation is
recorded as conflicted and left to the seller.

The inventory *label* (draft / active / sold) is different: it is Vendoo's
own tab for the item, not Studio's listing copy. Every successful ``get_item``
refreshes that label and the sidebar status, even when content is conflicted —
so a regenerate-then-relist in Vendoo flips Studio back to active without a
button.

Syncs run when the seller saves in Vendoo (the extension says so), when a
listing is opened, and when Studio regains focus — never on a timer. Each one
stamps the conversation so the editor can show when it last checked.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import Session

from vendoo_studio.repositories.queries import (
    BUSY_LISTING_STATUSES,
    ConversationRepo,
    JobRepo,
    ListingRepo,
    VENDOO_LISTING_STATUSES,
)

log = logging.getLogger("vendoo_studio.vendoo_watch")

SYNCED_AT = "vendooSyncedAt"
SYNCED_REVISION = "vendooSyncedRevision"
CHECKED_AT = "vendooCheckedAt"
SYNC_CONFLICT = "vendooSyncConflict"

__all__ = [
    "sync_state",
    "sync_conversation",
    "sync_status",
    "apply_pull",
    "studio_has_unpushed_edits",
    "cache_pulled_item",
    "refresh_inventory_label",
    "SYNCED_AT",
    "SYNCED_REVISION",
    "CHECKED_AT",
]

# One sync per conversation at a time: a seller save and a focus event landing
# together must not both pull and write two revisions.
_locks: dict[str, asyncio.Lock] = {}


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


def refresh_inventory_label(db: Session, conv_id: str, item: dict[str, Any]) -> str:
    """Adopt Vendoo's draft / active / sold label without touching listing fields.

    Safe during a content conflict: the sidebar tab is Vendoo's inventory state,
    not Studio's form copy. Returns the label applied.
    """
    from vendoo_studio.services.vendoo_import import (
        merge_notes,
        vendoo_dates,
        vendoo_item_status,
        vendoo_listed_marketplaces,
        vendoo_updated_at,
    )

    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        return "draft"
    status = vendoo_item_status(item, None)
    if status not in VENDOO_LISTING_STATUSES:
        status = "draft"
    conv.notes = merge_notes(conv.notes, {
        "vendooStatus": status,
        "vendooMarketplaces": vendoo_listed_marketplaces(item, None),
        "vendooDates": vendoo_dates(item, None),
        "vendooUpdatedAt": vendoo_updated_at(item, None),
    })
    db.commit()
    # A send in flight owns the row; leave its label alone until it settles.
    if conv.status not in BUSY_LISTING_STATUSES and conv.status != status:
        repo.update_status(conv_id, status)
    return status


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
    refresh_inventory_label(db, conv_id, item)
    db.refresh(conv)
    conv.notes = merge_notes(conv.notes, {
        SYNCED_AT: str(stamp),
        SYNCED_REVISION: str(revision_id or ""),
        CHECKED_AT: datetime.now(UTC).isoformat(),
        SYNC_CONFLICT: "",
    })
    db.commit()


def _mark_conflict(db: Session, conv_id: str, item: dict[str, Any]) -> None:
    """Both sides moved: keep Studio's fields, still take Vendoo's inventory label."""
    from vendoo_studio.services.vendoo_import import merge_notes

    refresh_inventory_label(db, conv_id, item)
    # Marketplace chips read the job draft cache; refresh them without saving
    # a listing revision so the form stays Studio's.
    cache_pulled_item(db, conv_id, item, source="vendoo_label")
    conv = ConversationRepo(db).get(conv_id)
    if not conv:
        return
    conv.notes = merge_notes(conv.notes, {
        CHECKED_AT: datetime.now(UTC).isoformat(),
        SYNC_CONFLICT: "1",
    })
    db.commit()


async def sync_conversation(db: Session, conv_id: str) -> dict[str, Any]:
    """Read the bound Vendoo item and pull it when that is safe.

    ``action`` is ``pull`` (Studio took Vendoo's version), ``conflict`` (both
    sides moved; listing fields were not overwritten), ``none``, or
    ``unavailable`` (Chrome or Vendoo could not be reached; nothing was
    recorded). Inventory labels refresh on every successful read.
    """
    from vendoo_studio.services.browser_bridge import BrowserBridgeError
    from vendoo_studio.services.vendoo_create import VendooCreateError, run_ops
    from vendoo_studio.services.vendoo_import import parse_notes, vendoo_binding

    lock = _locks.setdefault(conv_id, asyncio.Lock())
    async with lock:
        conv = ConversationRepo(db).get(conv_id)
        item_id = vendoo_binding(conv.notes if conv else None).get("vendooItemId")
        if not item_id:
            return {"action": "none", "reason": "no vendoo draft"}
        try:
            reply = await run_ops(SimpleNamespace(id=None), [{"op": "get_item", "item_id": item_id}])
        except (BrowserBridgeError, VendooCreateError) as exc:
            return {"action": "unavailable", "reason": str(exc) or "vendoo unavailable"}
        item = next((r.get("item") for r in reply.get("results", []) if r.get("op") == "get_item"), None)
        if not isinstance(item, dict):
            return {"action": "unavailable", "reason": "no item"}

        # Another request may have pulled while this one waited on Chrome.
        db.expire_all()
        state = sync_state(db, conv_id, item)
        result: dict[str, Any] = {"action": state["action"], "reason": state["reason"], "item_id": item_id}
        if state["action"] == "pull":
            result["revision_id"] = apply_pull(db, conv_id, item)
        elif state["action"] == "conflict":
            _mark_conflict(db, conv_id, item)
        else:
            mark_synced(db, conv_id, item, state.get("revision"))
        db.expire_all()
        conv = ConversationRepo(db).get(conv_id)
        result["vendoo_status"] = str(parse_notes(conv.notes if conv else None).get("vendooStatus") or "draft")
        return result


def sync_status(db: Session, conv_id: str) -> dict[str, Any]:
    """What the editor shows: when Studio last checked Vendoo and how it went."""
    from vendoo_studio.services.vendoo_import import parse_notes

    conv = ConversationRepo(db).get(conv_id)
    notes = parse_notes(conv.notes if conv else None)
    return {
        "checked_at": notes.get(CHECKED_AT) or None,
        "conflict": bool(notes.get(SYNC_CONFLICT)),
        "revision_id": notes.get(SYNCED_REVISION) or None,
    }
