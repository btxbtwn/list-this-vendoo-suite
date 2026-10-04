"""scout checks: "is this worth buying?" from photos

Revision ID: 3b803e1f23bd
Revises: 01c95d64842f
Create Date: 2026-10-04 04:13:47.103915
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '3b803e1f23bd'
down_revision = '01c95d64842f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('scout_checks',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('asking_price', sa.Float(), nullable=True),
    sa.Column('photos', sa.JSON(), nullable=False),
    sa.Column('title', sa.String(), nullable=True),
    sa.Column('analysis', sa.Text(), nullable=True),
    sa.Column('comps', sa.Text(), nullable=True),
    sa.Column('estimate', sa.Float(), nullable=True),
    sa.Column('comps_count', sa.Integer(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('decision', sa.String(), nullable=True),
    sa.Column('conversation_id', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('decided_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('scout_checks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_scout_checks_conversation_id'), ['conversation_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('scout_checks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_scout_checks_conversation_id'))

    op.drop_table('scout_checks')
