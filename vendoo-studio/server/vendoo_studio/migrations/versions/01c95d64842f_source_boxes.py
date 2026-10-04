"""wholesale boxes, and the box each listing came out of

Revision ID: 01c95d64842f
Revises: a8f2c91d4e10
Create Date: 2026-10-04 03:59:46.253454
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '01c95d64842f'
down_revision = 'a8f2c91d4e10'
branch_labels = None
depends_on = None

FK_NAME = 'fk_conversations_box_id_source_boxes'


def upgrade() -> None:
    op.create_table(
        'source_boxes',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('store', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('url', sa.String(), nullable=True),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('shipping', sa.Float(), nullable=False),
        sa.Column('pieces', sa.Integer(), nullable=True),
        sa.Column('bought_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('box_id', sa.String(), nullable=True))
        batch_op.create_index(batch_op.f('ix_conversations_box_id'), ['box_id'], unique=False)
        batch_op.create_foreign_key(FK_NAME, 'source_boxes', ['box_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.drop_constraint(FK_NAME, type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_conversations_box_id'))
        batch_op.drop_column('box_id')
    op.drop_table('source_boxes')
