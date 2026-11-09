import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.db.models import Contact, Conversation, Message, UsageCounter, UsageRecord
from src.usage.service import record_sent_message


@pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRESQL_DATABASE_URL"),
    reason="isolated PostgreSQL URL not provided",
)
def test_concurrent_replays_increment_once_and_do_not_lose_updates() -> None:
    url = os.environ["TEST_POSTGRESQL_DATABASE_URL"]
    engine = create_engine(url)
    phone = str(uuid4())
    with Session(engine) as session:
        contact = Contact(wa_id=uuid4().hex)
        conversation = Conversation(contact=contact)
        messages = [
            Message(
                conversation=conversation,
                direction="OUTBOUND",
                message_type="template",
                content={},
                wamid=str(uuid4()),
                delivery_status="SENT",
            )
            for _ in range(2)
        ]
        session.add_all(messages)
        session.commit()
        ids = [message.id for message in messages]

    barrier = Barrier(3)

    def worker(index: int) -> bool:
        with Session(engine) as session:
            barrier.wait(timeout=10)
            result = record_sent_message(
                session,
                ids[index],
                phone_number_id=phone,
                category="utility",
                sent_at=datetime(2035, 1, 1, tzinfo=UTC),
            )
            session.commit()
            return result

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(worker, index) for index in (0, 0, 1)]
        results = [future.result(timeout=30) for future in futures]
    assert sorted(results) == [False, True, True]
    with Session(engine) as session:
        counter = session.scalar(select(UsageCounter).where(UsageCounter.phone_number_id == phone))
        assert counter is not None and counter.quantity == 2
        records = session.scalars(
            select(UsageRecord).where(UsageRecord.message_id.in_(ids))
        ).all()
        assert len(records) == 2
    engine.dispose()
