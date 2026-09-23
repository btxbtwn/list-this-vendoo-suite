"""move the Vendoo draft cache out of job_events

Revision ID: a8f2c91d4e10
Revises: c3a71f0b5d42
Create Date: 2026-09-23 00:40:00.000000
"""
from __future__ import annotations

import json
from datetime import datetime, UTC

from alembic import op
import sqlalchemy as sa


revision = 'a8f2c91d4e10'
down_revision = 'c3a71f0b5d42'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep one status-only row per job and drop the appended draft events.

    Sync appended a whole Vendoo item to ``job_events`` on every pull. On the
    install that found this, the table had grown past 9 GB and Studio was
    failing with ``database or disk is full``. Only the marketplace statuses
    are ever read back, so only those are carried over.
    """
    from vendoo_studio.services.draft_cache import slim_vendoo_draft_payload

    op.create_table(
        'vendoo_draft_cache',
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('item_id', sa.String(), nullable=True),
        sa.Column('url', sa.String(), nullable=True),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('step', sa.String(), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
        sa.PrimaryKeyConstraint('job_id'),
    )

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        """
        SELECT job_id, step, payload
        FROM job_events
        WHERE event_type = 'vendoo_draft'
        ORDER BY job_id, created_at DESC, sequence DESC
        """
    )).fetchall()

    now = datetime.now(UTC).replace(tzinfo=None)
    seen: set[str] = set()
    for job_id, step, raw in rows:
        if job_id in seen:
            continue
        seen.add(job_id)
        try:
            draft = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            continue
        if not isinstance(draft, dict):
            continue
        bind.execute(
            sa.text(
                """
                INSERT INTO vendoo_draft_cache (job_id, item_id, url, source, step, payload, updated_at)
                VALUES (:job_id, :item_id, :url, :source, :step, :payload, :updated_at)
                """
            ),
            {
                "job_id": job_id,
                "item_id": draft.get("item_id"),
                "url": draft.get("url"),
                "source": draft.get("source") or "cache",
                "step": step,
                "payload": json.dumps(slim_vendoo_draft_payload(
                    item=draft.get("item"),
                    form=draft.get("form"),
                    statuses=draft.get("statuses"),
                )),
                "updated_at": now,
            },
        )

    bind.execute(sa.text("DELETE FROM job_events WHERE event_type = 'vendoo_draft'"))


def downgrade() -> None:
    """The events this replaced held data no build reads any more."""
    op.drop_table('vendoo_draft_cache')
