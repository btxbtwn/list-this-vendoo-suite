"""Preserve seller corrections, sale observations and measured outcomes.

Revision ID: 60bfc39e52d1
Revises: 47a52dece27b
"""
from alembic import op
import sqlalchemy as sa

revision = "60bfc39e52d1"
down_revision = "47a52dece27b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("listing_corrections",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("conversation_id", sa.String(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("revision_id", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("category_path", sa.String(), nullable=False),
        sa.Column("brand", sa.String(), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_listing_corrections_conversation_id", "listing_corrections", ["conversation_id"])
    op.create_table("sale_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("conversation_id", sa.String(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("sale_key", sa.String(), nullable=False),
        sa.Column("listing", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("conversation_id", "sale_key"),
    )
    op.create_index("ix_sale_snapshots_conversation_id", "sale_snapshots", ["conversation_id"])
    op.create_table("listing_evidence",
        sa.Column("conversation_id", sa.String(), sa.ForeignKey("conversations.id"), primary_key=True),
        sa.Column("shipping", sa.JSON(), nullable=True),
        sa.Column("engagement", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    raise RuntimeError("This migration is forward-only. Restore a pre-migration snapshot with the matching Studio version.")
