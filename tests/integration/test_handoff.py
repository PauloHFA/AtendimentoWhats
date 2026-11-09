from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.db.models import Base, Contact, Conversation, Ticket
from src.handoff.service import HandoffError, list_open_tickets, return_to_bot, take_for_human

NOW = datetime(2030, 1, 1, tzinfo=UTC)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def conversation_for(session: Session, status: str = "BOT") -> Conversation:
    contact = Contact(wa_id="15550000001")
    conversation = Conversation(contact=contact, status=status, state="faq")
    session.add(conversation)
    session.commit()
    return conversation


def test_handoff_creates_ticket_once_and_marks_conversation_human(session: Session) -> None:
    conversation = conversation_for(session)
    ticket = take_for_human(session, conversation.id, reason="Cliente solicitou", summary="Pedido")
    assert ticket.reason == "Cliente solicitou"
    assert ticket.summary == "Pedido"
    assert ticket.status == "OPEN"
    assert conversation.status == "HUMAN"
    again = take_for_human(session, conversation.id, reason="Outra solicitação")
    assert again.id == ticket.id
    assert len(session.scalars(select(Ticket)).all()) == 1


def test_return_to_bot_closes_ticket_and_resets_step(session: Session) -> None:
    conversation = conversation_for(session)
    ticket = take_for_human(session, conversation.id, reason="Solicitação")
    returned = return_to_bot(session, conversation.id, at=NOW)
    assert returned.status == "BOT"
    assert returned.state == "menu"
    assert ticket.status == "CLOSED"
    assert ticket.closed_at == NOW
    new_ticket = take_for_human(session, conversation.id, reason="Nova solicitação")
    assert new_ticket.id != ticket.id


def test_handoff_changes_roll_back_with_caller_transaction(session: Session) -> None:
    conversation = conversation_for(session)
    identifier = conversation.id
    take_for_human(session, identifier, reason="Solicitação")
    session.rollback()
    assert session.get(Conversation, identifier).status == "BOT"
    assert session.scalars(select(Ticket)).all() == []


def test_invalid_transitions_and_invalid_reasons_fail(session: Session) -> None:
    conversation = conversation_for(session, "CLOSED")
    with pytest.raises(HandoffError, match="closed"):
        take_for_human(session, conversation.id, reason="Solicitação")
    conversation.status = "BOT"
    with pytest.raises(HandoffError, match="reason"):
        take_for_human(session, conversation.id, reason=" ")
    with pytest.raises(HandoffError, match="human"):
        return_to_bot(session, conversation.id, at=NOW)


def test_inconsistent_human_ownership_and_naive_time_are_rejected(session: Session) -> None:
    conversation = conversation_for(session, "HUMAN")
    with pytest.raises(HandoffError, match="no open ticket"):
        take_for_human(session, conversation.id, reason="Solicitação")
    with pytest.raises(HandoffError, match="no open ticket"):
        return_to_bot(session, conversation.id, at=NOW)
    with pytest.raises(HandoffError, match="timezone"):
        return_to_bot(session, conversation.id, at=datetime(2030, 1, 1))


def test_queue_lists_open_tickets_in_order_and_paginates(session: Session) -> None:
    conversation = conversation_for(session)
    first = take_for_human(session, conversation.id, reason="Primeira")
    first.created_at = NOW
    return_to_bot(session, conversation.id, at=NOW)
    second = take_for_human(session, conversation.id, reason="Segunda")
    second.created_at = NOW + timedelta(minutes=2)
    other = Contact(wa_id="15550000002")
    another_conversation = Conversation(contact=other, status="BOT", state="faq")
    session.add(another_conversation)
    session.flush()
    third = take_for_human(session, another_conversation.id, reason="Terceira")
    third.created_at = NOW + timedelta(minutes=1)
    session.flush()
    assert [ticket.id for ticket in list_open_tickets(session)] == [third.id, second.id]
    assert [ticket.id for ticket in list_open_tickets(session, limit=1, offset=1)] == [second.id]
    assert list_open_tickets(session, offset=2) == []


@pytest.mark.parametrize(("limit", "offset"), [(0, 0), (101, 0), (1, -1)])
def test_queue_rejects_invalid_pagination(session: Session, limit: int, offset: int) -> None:
    with pytest.raises(HandoffError, match="limit"):
        list_open_tickets(session, limit=limit, offset=offset)
