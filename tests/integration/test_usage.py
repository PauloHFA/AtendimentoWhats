from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.db.models import Base, Contact, Conversation, Message, UsageCounter, UsageRecord
from src.usage.service import UsageError, record_sent_message

SENT_AT = datetime(2035, 1, 31, 23, 30, tzinfo=UTC)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def outbound(session: Session, *, status: str = "SENT") -> Message:
    contact = Contact(wa_id=uuid4().hex)
    conversation = Conversation(contact=contact)
    message = Message(
        conversation=conversation,
        direction="OUTBOUND",
        message_type="template",
        content={},
        wamid=str(uuid4()),
        delivery_status=status,
    )
    session.add(message)
    session.commit()
    return message


def record(session: Session, message: Message, **overrides: object) -> bool:
    phone_number_id = str(overrides.get("phone_number_id", "123"))
    category = str(overrides.get("category", "utility"))
    sent_at = overrides.get("sent_at", SENT_AT)
    assert isinstance(sent_at, datetime)
    return record_sent_message(
        session, message.id, phone_number_id=phone_number_id, category=category, sent_at=sent_at
    )


def test_count_once_group_by_month_number_and_category(session: Session) -> None:
    one = outbound(session)
    two = outbound(session)
    three = outbound(session)
    assert record(session, one)
    assert not record(session, one)
    assert record(session, two)
    assert record(session, three, category="marketing", phone_number_id="456")
    counters = session.scalars(select(UsageCounter)).all()
    assert sorted((c.phone_number_id, c.category, c.quantity) for c in counters) == [
        ("123", "utility", 2),
        ("456", "marketing", 1),
    ]
    assert one.billing_category == "utility"
    assert counters[0].month == SENT_AT.date().replace(day=1)


def test_utc_month_and_conflicting_replay(session: Session) -> None:
    message = outbound(session)
    local_time = datetime(2035, 2, 1, 1, 30, tzinfo=timezone(timedelta(hours=2)))
    assert record(session, message, sent_at=local_time)
    assert not record(session, message, sent_at=SENT_AT)
    assert session.scalar(select(UsageCounter)).month == SENT_AT.date().replace(day=1)
    with pytest.raises(UsageError, match="different usage details"):
        record(session, message, phone_number_id="other")


def test_usage_rolls_back_with_message_category(session: Session) -> None:
    message = outbound(session)
    assert record(session, message)
    session.rollback()
    assert session.scalars(select(UsageCounter)).all() == []
    assert session.scalars(select(UsageRecord)).all() == []
    assert session.get(Message, message.id).billing_category is None


@pytest.mark.parametrize("status", ["PENDING", "FAILED", "SIMULATED"])
def test_unconfirmed_or_simulated_messages_are_not_counted(session: Session, status: str) -> None:
    message = outbound(session, status=status)
    with pytest.raises(UsageError, match="confirmed"):
        record(session, message)
    assert session.scalars(select(UsageCounter)).all() == []


def test_invalid_records_are_rejected(session: Session) -> None:
    message = outbound(session)
    for overrides in (
        {"phone_number_id": ""},
        {"phone_number_id": " x "},
        {"category": "unexpected"},
        {"sent_at": datetime(2035, 1, 1)},
    ):
        with pytest.raises(UsageError):
            record(session, message, **overrides)
    message.direction = "INBOUND"
    with pytest.raises(UsageError, match="outbound"):
        record(session, message)
    assert session.scalars(select(UsageRecord)).all() == []
