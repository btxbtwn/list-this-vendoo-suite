"""Sale calendar plans, preserving marketplace event history.

Revision ID: 47a52dece27b
Revises: 26082cbdc6ea
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime

from alembic import op
import sqlalchemy as sa

revision = '47a52dece27b'
down_revision = '26082cbdc6ea'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    previous = bind.execute(sa.text('SELECT * FROM sale_events')).mappings().all()
    # Like SQLite batch mode, build the new shape before replacing the table.
    # There are no foreign keys to sale_events. Keep the original id on the
    # first marketplace record and split multi-marketplace histories explicitly.
    table = op.create_table('sale_calendar_events',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('marketplace', sa.String(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('timezone', sa.String(), nullable=False),
        sa.Column('discount_percent', sa.Float(), nullable=True),
        sa.Column('fee_percent', sa.Float(), nullable=True),
        sa.Column('shipping_cost', sa.Float(), nullable=True),
        sa.Column('minimum_profit', sa.Float(), nullable=True),
        sa.Column('items', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    now = datetime.now(UTC)
    for row in previous:
        markets = json.loads(row['marketplaces']) if isinstance(row['marketplaces'], str) else row['marketplaces']
        markets = list(dict.fromkeys(markets or ['all']))
        start = date.fromisoformat(str(row['starts_on']))
        end = date.fromisoformat(str(row['ends_on']))
        created = datetime.fromisoformat(str(row['created_at'])) if row['created_at'] else now
        for index, market in enumerate(markets):
            bind.execute(table.insert().values(
                id=row['id'] if index == 0 else uuid.uuid4().hex[:12],
                title=row['name'], marketplace=market,
                start_date=start, end_date=end, timezone='UTC',
                discount_percent=row['discount_percent'], items=[],
                status='planned' if start > now.date() else 'ran',
                notes='Saved from earlier sale history. Dates were preserved; UTC is assumed because the original time zone was not recorded. Edit this record to set its event time zone.',
                created_at=created, updated_at=now,
            ))
    op.drop_table('sale_events')
    op.rename_table('sale_calendar_events', 'sale_events')


def downgrade() -> None:
    raise RuntimeError('This migration is forward-only. Restore a pre-migration snapshot with the matching Studio version.')
