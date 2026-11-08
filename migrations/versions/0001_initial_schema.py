"""Create initial customer support schema.

Revision ID: 0001_initial_schema
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contacts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("wa_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("marketing_consent", sa.Boolean(), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opt_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_contacts_wa_id", "contacts", ["wa_id"], unique=True)

    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("contact_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("session_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_conversations_contact_status", "conversations", ["contact_id", "status"]
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("conversation_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("wamid", sa.String(length=255), nullable=True),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("message_type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("billing_category", sa.String(length=32), nullable=True),
        sa.Column("delivery_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_messages_wamid", "messages", ["wamid"], unique=True)
    op.create_index(
        "ix_messages_conversation_created", "messages", ["conversation_id", "created_at"]
    )

    op.create_table(
        "tickets",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("conversation_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("assignee", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "appointments",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("contact_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("service", sa.String(length=255), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_appointments_contact_start", "appointments", ["contact_id", "starts_at"]
    )

    op.create_table(
        "knowledge_articles",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("wamid", sa.String(length=255), nullable=True),
        sa.Column("dedupe_key", sa.String(length=512), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index("ix_webhook_events_wamid", "webhook_events", ["wamid"], unique=False)
    op.create_index(
        "ix_webhook_events_dedupe_key",
        "webhook_events",
        ["dedupe_key"],
        unique=True,
    )

    op.create_table(
        "usage_counters",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("phone_number_id", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "month", "phone_number_id", "category", name="uq_usage_month_number_category"
        ),
    )


def downgrade() -> None:
    op.drop_table("usage_counters")
    op.drop_index("ix_webhook_events_dedupe_key", table_name="webhook_events")
    op.drop_index("ix_webhook_events_wamid", table_name="webhook_events")
    op.drop_table("webhook_events")
    op.drop_table("knowledge_articles")
    op.drop_index("ix_appointments_contact_start", table_name="appointments")
    op.drop_table("appointments")
    op.drop_table("tickets")
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_index("ix_messages_wamid", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_contact_status", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_contacts_wa_id", table_name="contacts")
    op.drop_table("contacts")
