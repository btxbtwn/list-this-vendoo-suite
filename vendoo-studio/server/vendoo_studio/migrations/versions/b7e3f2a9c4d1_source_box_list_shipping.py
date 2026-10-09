"""the carrier list rate a bought box's shipping was estimated from

Revision ID: b7e3f2a9c4d1
Revises: 7c4d2e9f1a35
Create Date: 2026-10-09 06:30:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b7e3f2a9c4d1'
down_revision = '7c4d2e9f1a35'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('source_boxes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('list_shipping', sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('source_boxes', schema=None) as batch_op:
        batch_op.drop_column('list_shipping')
