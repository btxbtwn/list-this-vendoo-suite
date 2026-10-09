"""backfill the revision each linked listing was last level with Vendoo on

Revision ID: 5e8b3c0d9a17
Revises: 9d4e7a2b1c60
"""
from __future__ import annotations

from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision = "5e8b3c0d9a17"
down_revision = "9d4e7a2b1c60"
branch_labels = None
depends_on = None


def _epoch_ms(created_at) -> str:
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    return str(int(created_at.replace(tzinfo=UTC).timestamp() * 1000))


def upgrade() -> None:
    """Give imported listings the sync baseline imports now record themselves.

    Unsent edits are measured from the revision Studio and Vendoo were last
    level on. Imports made before they recorded one have none, so nothing done
    to them reads as unsent, and the first sync through Chrome pulls Vendoo's
    copy over whatever Studio changed. Their newest import is Vendoo's copy as
    of the import. A listing Regenerate or Clear wiped back to a blank revision
    lost that copy with it; the blank stands in, since Vendoo still holds the
    old listing and anything filled in since is ahead of it.
    """
    from vendoo_studio.services.vendoo_import import merge_notes, parse_notes
    from vendoo_studio.services.vendoo_watch import SYNCED_AT, SYNCED_REVISION

    bind = op.get_bind()
    conversations = bind.execute(sa.text(
        "SELECT id, notes FROM conversations WHERE notes LIKE '%vendooItemId%'"
    )).fetchall()

    for conv_id, notes in conversations:
        parsed = parse_notes(notes)
        if not parsed.get("vendooItemId") or parsed.get(SYNCED_REVISION):
            continue
        revisions = bind.execute(
            sa.text(
                "SELECT id, source, created_at FROM listing_revisions "
                "WHERE conversation_id = :id ORDER BY created_at, rowid"
            ),
            {"id": conv_id},
        ).fetchall()
        imports = [row for row in revisions if row.source == "vendoo_import"]
        if imports:
            baseline = imports[-1]
        elif revisions and revisions[0].source == "reset":
            baseline = revisions[0]
        else:
            continue
        updates = {SYNCED_REVISION: baseline.id}
        if not parsed.get(SYNCED_AT) and baseline.created_at:
            updates[SYNCED_AT] = _epoch_ms(baseline.created_at)
        bind.execute(
            sa.text("UPDATE conversations SET notes = :notes WHERE id = :id"),
            {"notes": merge_notes(notes, updates), "id": conv_id},
        )


def downgrade() -> None:
    raise RuntimeError("This migration is forward-only. Restore a pre-migration snapshot with the matching Studio version.")
