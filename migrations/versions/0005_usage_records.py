"""Create idempotency records for usage counters.

Revision ID: 0005_usage_records
Revises: 0004_consent_history
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_usage_records"
down_revision: str | None = "0004_consent_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_records",
        sa.Column("message_id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("phone_number_id", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM usage_records LIMIT 1")).first() is not None:
        raise RuntimeError("Cannot downgrade while usage records exist; replay could double-count")
    op.drop_table("usage_records")
