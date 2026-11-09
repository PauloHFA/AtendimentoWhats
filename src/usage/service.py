from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.postgresql.dml import Insert as PostgreSQLInsert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.sqlite.dml import Insert as SQLiteInsert
from sqlalchemy.orm import Session

from src.db.models import Message, UsageCounter, UsageRecord

_CATEGORIES = frozenset({"marketing", "utility", "authentication", "service"})


class UsageError(ValueError):
    """The usage record is invalid or conflicts with an earlier record."""


def _insert_for(
    dialect: str, table: type[UsageRecord] | type[UsageCounter]
) -> PostgreSQLInsert | SQLiteInsert:
    if dialect == "postgresql":
        return postgresql_insert(table)
    if dialect == "sqlite":
        return sqlite_insert(table)
    raise RuntimeError(f"Unsupported usage database dialect: {dialect}")


def record_sent_message(
    session: Session,
    message_id: UUID,
    *,
    phone_number_id: str,
    category: str,
    sent_at: datetime,
) -> bool:
    if (
        not phone_number_id
        or phone_number_id != phone_number_id.strip()
        or len(phone_number_id) > 64
    ):
        raise UsageError("phone number id must contain 1 to 64 non-padding characters")
    if category not in _CATEGORIES:
        raise UsageError("unknown usage category")
    if sent_at.tzinfo is None or sent_at.utcoffset() is None:
        raise UsageError("sent time must include a timezone")
    month = sent_at.astimezone(UTC).date().replace(day=1)
    message = session.scalar(select(Message).where(Message.id == message_id).with_for_update())
    if message is None or message.direction != "OUTBOUND" or not message.wamid:
        raise UsageError("a persisted outbound message with a channel message id is required")
    if message.delivery_status not in {"SENT", "DELIVERED", "READ"}:
        raise UsageError("message must have a confirmed sent status")
    if message.billing_category is not None and message.billing_category != category:
        raise UsageError("message category conflicts with the usage record")

    dialect = session.get_bind().dialect.name
    statement = (
        _insert_for(dialect, UsageRecord)
        .values(
            message_id=message_id, month=month, phone_number_id=phone_number_id, category=category
        )
        .on_conflict_do_nothing(index_elements=[UsageRecord.message_id])
        .returning(UsageRecord.message_id)
    )
    inserted = session.scalar(statement)
    if inserted is None:
        previous = session.get(UsageRecord, message_id)
        if previous is None:
            raise RuntimeError("usage record conflict without an existing record")
        if (previous.month, previous.phone_number_id, previous.category) != (
            month, phone_number_id, category
        ):
            raise UsageError("message already recorded with different usage details")
        return False

    statement_counter = _insert_for(dialect, UsageCounter).values(
        id=uuid4(), month=month, phone_number_id=phone_number_id, category=category, quantity=1
    )
    statement_counter = statement_counter.on_conflict_do_update(
        index_elements=[UsageCounter.month, UsageCounter.phone_number_id, UsageCounter.category],
        set_={"quantity": UsageCounter.quantity + 1},
    )
    session.execute(statement_counter)
    message.billing_category = category
    session.flush()
    return True
