"""Drop seller-entered packed shipping and buyer-response reports.

Revision ID: 9d4e7a2b1c60
Revises: 60bfc39e52d1
"""
from alembic import op

revision = "9d4e7a2b1c60"
down_revision = "60bfc39e52d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("listing_evidence")


def downgrade() -> None:
    raise RuntimeError("This migration is forward-only. Restore a pre-migration snapshot with the matching Studio version.")
