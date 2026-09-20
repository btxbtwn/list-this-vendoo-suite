"""backfill each conversation's listed marketplaces

Revision ID: c3a71f0b5d42
Revises: b07d34ffaad6
Create Date: 2026-09-20 11:10:00.000000
"""
from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = 'c3a71f0b5d42'
down_revision = 'eb12154c8bb2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Record, per conversation, the marketplaces its Vendoo item is live on.

    Imports write this into the conversation's notes from now on; the inventory
    already on disk was imported before the sidebar filtered on it, and the only
    place that state exists is inside the cached draft payloads.
    """
    from vendoo_studio.services.vendoo_import import (
        merge_notes,
        parse_notes,
        vendoo_listed_marketplaces,
    )

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        """
        SELECT c.id, c.notes, e.payload
        FROM conversations c
        JOIN jobs j ON j.conversation_id = c.id
        JOIN job_events e ON e.job_id = j.id AND e.event_type = 'vendoo_draft'
        ORDER BY c.id, e.created_at DESC, e.sequence DESC
        """
    )).fetchall()

    seen: set[str] = set()
    for conv_id, notes, payload in rows:
        if conv_id in seen:
            continue
        if "vendooMarketplaces" in parse_notes(notes):
            seen.add(conv_id)
            continue
        try:
            draft = json.loads(payload) if isinstance(payload, str) else payload
        except ValueError:
            continue
        if not isinstance(draft, dict):
            continue
        item = draft.get("item") if isinstance(draft.get("item"), dict) else None
        form = draft.get("form") if isinstance(draft.get("form"), dict) else None
        if item is None and form is None:
            continue
        seen.add(conv_id)
        bind.execute(
            sa.text("UPDATE conversations SET notes = :notes WHERE id = :id"),
            {
                "notes": merge_notes(notes, {
                    "vendooMarketplaces": vendoo_listed_marketplaces(item, form),
                }),
                "id": conv_id,
            },
        )


def downgrade() -> None:
    """Notes are additive; the backfilled key is left in place."""
