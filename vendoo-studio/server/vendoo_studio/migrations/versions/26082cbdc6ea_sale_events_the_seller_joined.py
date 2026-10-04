"""sale events the seller joined

Revision ID: 26082cbdc6ea
Revises: 3b803e1f23bd
Create Date: 2026-10-04 12:55:08.771289
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '26082cbdc6ea'
down_revision = '3b803e1f23bd'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('sale_events',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('starts_on', sa.Date(), nullable=False),
    sa.Column('ends_on', sa.Date(), nullable=False),
    sa.Column('discount_percent', sa.Integer(), nullable=True),
    sa.Column('marketplaces', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('sale_events')
