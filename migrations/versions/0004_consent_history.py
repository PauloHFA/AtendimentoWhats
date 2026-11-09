"""Add consent event history.

Revision ID: 0004_consent_history
Revises: 0003_appointment_slot
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_consent_history"
down_revision: str | None = "0003_appointment_slot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "consent_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("contact_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_consent_events_contact_id", "consent_events", ["contact_id"])


def downgrade() -> None:
    op.drop_index("ix_consent_events_contact_id", table_name="consent_events")
    op.drop_table("consent_events")
