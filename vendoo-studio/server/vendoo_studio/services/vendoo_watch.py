"""Keep a bound listing in step with its Vendoo draft.

Vendoo stamps every item with ``dateLastModified``, so noticing a change there
is a matter of comparing it against what Studio last saw. When Vendoo moved:

- If only inventory status / dates changed (listed, sold, stamps), refresh the
  sidebar label and marketplace chips — leave Studio's listing fields alone.
- If form content changed, take Vendoo's copy, including over Studio's unpushed
  edits. That matches listing or editing in Vendoo, then opening Studio.

Studio-only edits are left alone until Vendoo moves or the seller pushes
(Update / Send).

Syncs run when the seller saves in Vendoo (the extension says so), when a
listing is opened, and when Studio regains focus — never on a timer. Each one
stamps the conversation so the editor can show when it last checked.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import Session

from vendoo_studio.repositories.queries import (
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
CONTENT_FINGERPRINT = "vendooContentFingerprint"

__all__ = [
    "sync_state",
    "sync_conversation",
    "sync_status",
    "apply_pull",
    "studio_has_unpushed_edits",
    "cache_pulled_item",
    "refresh_inventory_label",
    "item_content_fingerprint",
    "SYNCED_AT",
    "SYNCED_REVISION",
    "CHECKED_AT",
    "CONTENT_FINGERPRINT",
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


def _hash_payload(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def listing_content_fingerprint(listing: dict[str, Any] | None) -> str:
    """Stable hash of Studio listing fields (no inventory status)."""
    return _hash_payload(listing or {})


def item_content_fingerprint(item: dict[str, Any] | None) -> str:
    """Hash of the form content Studio would pull from this Vendoo item.

    Inventory status and date stamps are excluded: listing on a marketplace
    bumps ``dateLastModified`` without changing title, specifics, or photos.
    """
    from vendoo_studio.services.vendoo_import import listing_from_vendoo, vendoo_image_records

    listing = listing_from_vendoo(item, None)
    images: list[str] = []
    for record in vendoo_image_records(item, None):
        if isinstance(record, dict):
            images.append(str(record.get("id") or record.get("url") or ""))
        else:
            images.append(str(record or ""))
    return _hash_payload({"listing": listing, "images": images})


def studio_has_unpushed_edits(db: Session, conv_id: str) -> bool:
    """True when Studio's current revision is ahead of the last synced one."""
    from vendoo_studio.services.vendoo_import import parse_notes

    conv = ConversationRepo(db).get(conv_id)
    notes = parse_notes(conv.notes if conv else None)
    revisions = ListingRepo(db).get_revisions(conv_id)
    local_revision = revisions[0].id if revisions else None
    synced_revision = str(notes.get(SYNCED_REVISION) or "")
    return bool(local_revision and synced_revision and local_revision != synced_revision)


def _vendoo_content_unchanged(db: Session, conv_id: str, item: dict[str, Any], notes: dict[str, Any]) -> bool:
    """True when Vendoo's form content matches what Studio last synced."""
    from vendoo_studio.services.vendoo_import import listing_from_vendoo

    fresh = item_content_fingerprint(item)
    seen = str(notes.get(CONTENT_FINGERPRINT) or "")
    if seen:
        return seen == fresh

    # Older conversations: compare the pulled listing shape to the synced revision.
    synced_revision = str(notes.get(SYNCED_REVISION) or "")
    if not synced_revision:
        return False
    for revision in ListingRepo(db).get_revisions(conv_id):
        if revision.id == synced_revision:
            return listing_content_fingerprint(listing_from_vendoo(item, None)) == listing_content_fingerprint(
                revision.listing_json if isinstance(revision.listing_json, dict) else {}
            )
    return False


def sync_state(db: Session, conv_id: str, item: dict[str, Any]) -> dict[str, Any]:
    """What, if anything, should happen for this conversation.

    ``action`` is ``pull`` (Vendoo form content moved), ``label`` (only status
    or dates moved), or ``none``.
    """
    from vendoo_studio.services.vendoo_import import parse_notes

    conv = ConversationRepo(db).get(conv_id)
    notes = parse_notes(conv.notes if conv else None)
    seen = _stamp(notes.get(SYNCED_AT))
    remote = _stamp((item or {}).get("dateLastModified"))

    revisions = ListingRepo(db).get_revisions(conv_id)
    local_revision = revisions[0].id if revisions else None
    remote_moved = bool(remote and seen and remote > seen)

    if not seen:
        return {"action": "pull", "reason": "first sync", "remote": remote, "revision": local_revision}
    if remote_moved and _vendoo_content_unchanged(db, conv_id, item, notes):
        return {"action": "label", "reason": "status only", "remote": remote, "revision": local_revision}
    if remote_moved:
        reason = (
            "both changed, prefer vendoo"
            if studio_has_unpushed_edits(db, conv_id)
            else "vendoo changed"
        )
        return {"action": "pull", "reason": reason, "remote": remote, "revision": local_revision}
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

    The sidebar tab is Vendoo's inventory state, not Studio's form copy.
    Returns the label applied.
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
    # A label read is Vendoo's bookkeeping, not the seller's activity: the
    # sweep passes over the whole inventory, and restamping updated_at on each
    # item would rotate the sidebar's "Recent activity" order page by page. A
    # real label change still surfaces, through the status write below.
    repo.write_notes(conv_id, merge_notes(conv.notes, {
        "vendooStatus": status,
        "vendooMarketplaces": vendoo_listed_marketplaces(item, None),
        "vendooDates": vendoo_dates(item, None),
        "vendooUpdatedAt": vendoo_updated_at(item, None),
    }), bump_updated_at=False)
    # Generation owns ``in_progress``. A send owns ``listing`` only while a job
    # is still open — otherwise adopt Vendoo's label (fixes a stuck Listing badge
    # after the marketplaces are already live).
    send_in_flight = conv.status == "listing" and any(
        job.conversation_id == conv_id for job in JobRepo(db).get_active()
    )
    if conv.status == "in_progress":
        return status
    if not send_in_flight and conv.status != status:
        repo.update_status(conv_id, status)
    return status


def apply_label_sync(db: Session, conv_id: str, item: dict[str, Any]) -> None:
    """Vendoo only moved status/dates: refresh chips and stamp, keep listing fields."""
    from vendoo_studio.services.vendoo_import import merge_notes

    refresh_inventory_label(db, conv_id, item)
    cache_pulled_item(db, conv_id, item, source="vendoo_label")
    conv = ConversationRepo(db).get(conv_id)
    if not conv:
        return
    stamp = _stamp((item or {}).get("dateLastModified")) or int(
        datetime.now(UTC).timestamp() * 1000
    )
    # Keep SYNCED_REVISION: Studio may still have unpushed edits.
    conv.notes = merge_notes(conv.notes, {
        SYNCED_AT: str(stamp),
        CHECKED_AT: datetime.now(UTC).isoformat(),
        SYNC_CONFLICT: "",
        CONTENT_FINGERPRINT: item_content_fingerprint(item),
    })
    db.commit()


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
        CONTENT_FINGERPRINT: item_content_fingerprint(item),
    })
    db.commit()


async def sync_conversation(db: Session, conv_id: str) -> dict[str, Any]:
    """Read the bound Vendoo item and pull or label-refresh as needed.

    ``action`` is ``pull`` (form content from Vendoo), ``label`` (status/dates
    only), ``none``, or ``unavailable``. When form content moved, Vendoo wins.
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
        elif state["action"] == "label":
            apply_label_sync(db, conv_id, item)
        else:
            mark_synced(db, conv_id, item, state.get("revision"))
        # Best-effort: grow leaf + LLM schema caches from this draft's categories.
        try:
            from vendoo_studio.services.category_learn import learn_category_schemas_from_item

            learned = await learn_category_schemas_from_item(db, item)
            if learned.get("learned"):
                result["schemas_learned"] = learned["learned"]
        except Exception:  # noqa: BLE001 - sync succeeded; cache growth is optional
            log.info("category schema learn skipped after sync", exc_info=True)
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
        # Cleared on every successful sync; kept so older notes still deserialize.
        "conflict": bool(notes.get(SYNC_CONFLICT)),
        "revision_id": notes.get(SYNCED_REVISION) or None,
    }
