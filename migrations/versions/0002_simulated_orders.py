"""Add simulated order lookup.

Revision ID: 0002_simulated_orders
Revises: 0001_initial_schema
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_simulated_orders"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "simulated_orders",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("number", sa.String(length=20), nullable=False, unique=True),
        sa.Column("contact_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=255), nullable=False),
        sa.Column("expected_date", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("simulated_orders")
