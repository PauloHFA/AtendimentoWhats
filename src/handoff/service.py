from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Conversation, Ticket


class HandoffError(ValueError):
    """A handoff cannot be performed from the current state."""


def list_open_tickets(session: Session, *, limit: int = 50, offset: int = 0) -> list[Ticket]:
    if not 1 <= limit <= 100 or offset < 0:
        raise HandoffError("limit must be between 1 and 100 and offset must be non-negative")
    return list(
        session.scalars(
            select(Ticket)
            .where(Ticket.status == "OPEN")
            .order_by(Ticket.created_at, Ticket.id)
            .limit(limit)
            .offset(offset)
        )
    )


def _lock_conversation(session: Session, conversation_id: UUID) -> Conversation:
    conversation = session.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if conversation is None:
        raise HandoffError("conversation not found")
    return conversation


def _open_ticket(session: Session, conversation_id: UUID) -> Ticket | None:
    tickets = list(
        session.scalars(
            select(Ticket).where(
                Ticket.conversation_id == conversation_id, Ticket.status == "OPEN"
            )
        )
    )
    if len(tickets) > 1:
        raise HandoffError("conversation has multiple open tickets")
    return tickets[0] if tickets else None


def take_for_human(
    session: Session, conversation_id: UUID, *, reason: str, summary: str | None = None
) -> Ticket:
    reason = reason.strip()
    if not reason:
        raise HandoffError("reason must not be empty")
    conversation = _lock_conversation(session, conversation_id)
    if conversation.status == "CLOSED":
        raise HandoffError("closed conversation cannot be handed off")
    if conversation.status not in {"BOT", "HUMAN"}:
        raise HandoffError("unknown conversation status")
    ticket = _open_ticket(session, conversation_id)
    if ticket is not None:
        if conversation.status != "HUMAN":
            raise HandoffError("open ticket requires human ownership")
        return ticket
    if conversation.status == "HUMAN":
        raise HandoffError("human-owned conversation has no open ticket")
    ticket = Ticket(conversation_id=conversation_id, reason=reason, summary=summary, status="OPEN")
    session.add(ticket)
    conversation.status = "HUMAN"
    session.flush()
    return ticket


def return_to_bot(
    session: Session, conversation_id: UUID, *, at: datetime | None = None
) -> Conversation:
    now = at if at is not None else datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise HandoffError("timestamp must include a timezone")
    conversation = _lock_conversation(session, conversation_id)
    if conversation.status != "HUMAN":
        raise HandoffError("only a human-owned conversation can return to the bot")
    ticket = _open_ticket(session, conversation_id)
    if ticket is None:
        raise HandoffError("human-owned conversation has no open ticket")
    ticket.status = "CLOSED"
    ticket.closed_at = now
    conversation.status = "BOT"
    conversation.state = "menu"
    conversation.session_expires_at = now + timedelta(minutes=30)
    session.flush()
    return conversation
