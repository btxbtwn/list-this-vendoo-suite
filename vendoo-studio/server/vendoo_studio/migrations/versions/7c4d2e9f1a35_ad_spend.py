"""ad spend copied from Poshmark Promoted Closet and Etsy Ads

Revision ID: 7c4d2e9f1a35
Revises: 5e8b3c0d9a17
Create Date: 2026-10-09 12:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '7c4d2e9f1a35'
down_revision = '5e8b3c0d9a17'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ad_spend',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('marketplace', sa.String(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('spend', sa.Float(), nullable=False),
        sa.Column('clicks', sa.Integer(), nullable=True),
        sa.Column('orders', sa.Integer(), nullable=True),
        sa.Column('revenue', sa.Float(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('ad_spend')
