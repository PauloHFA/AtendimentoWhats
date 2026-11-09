import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.db.models import Contact, Conversation, Ticket
from src.handoff.service import take_for_human


@pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRESQL_DATABASE_URL"),
    reason="isolated PostgreSQL URL not provided",
)
def test_concurrent_handoff_creates_only_one_ticket() -> None:
    engine = create_engine(os.environ["TEST_POSTGRESQL_DATABASE_URL"])
    with Session(engine) as session:
        conversation = Conversation(contact=Contact(wa_id=uuid4().hex))
        session.add(conversation)
        session.commit()
        conversation_id = conversation.id

    barrier = Barrier(2)

    def worker() -> str:
        with Session(engine) as session:
            barrier.wait(timeout=10)
            ticket = take_for_human(session, conversation_id, reason="Solicitação")
            ticket_id = str(ticket.id)
            session.commit()
            return ticket_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert results[0] == results[1]
    with Session(engine) as session:
        conversation = session.get(Conversation, conversation_id)
        assert conversation is not None and conversation.status == "HUMAN"
        tickets = session.scalars(
            select(Ticket).where(Ticket.conversation_id == conversation_id)
        ).all()
        assert len(tickets) == 1
        assert tickets[0].status == "OPEN"
    engine.dispose()
