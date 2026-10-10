"""the business assistant's conversation

Revision ID: d2f6a80c3b91
Revises: b7e3f2a9c4d1
Create Date: 2026-10-10 12:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'd2f6a80c3b91'
down_revision = 'b7e3f2a9c4d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'assistant_messages',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('provider', sa.String(), nullable=True),
        sa.Column('model', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assistant_messages_created_at'), 'assistant_messages', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_assistant_messages_created_at'), table_name='assistant_messages')
    op.drop_table('assistant_messages')
