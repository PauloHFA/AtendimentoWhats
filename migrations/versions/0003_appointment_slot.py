"""Prevent duplicate simulated appointments.

Revision ID: 0003_appointment_slot
Revises: 0002_simulated_orders
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_appointment_slot"
down_revision: str | None = "0002_simulated_orders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_appointments_booked_service_start",
        "appointments",
        ["service", "starts_at"],
        unique=True,
        postgresql_where=sa.text("status = 'BOOKED'"),
        sqlite_where=sa.text("status = 'BOOKED'"),
    )


def downgrade() -> None:
    op.drop_index("uq_appointments_booked_service_start", table_name="appointments")
