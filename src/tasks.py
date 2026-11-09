from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any
from uuid import UUID

from kombu.exceptions import OperationalError
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.celery_app import celery_app
from src.channel.simulator import SimulatorAdapter
from src.config import get_settings
from src.consent.service import StaleOptInError, record_marketing_opt_in, record_opt_out
from src.db.models import Contact, Conversation, KnowledgeArticle, Message, WebhookEvent
from src.db.session import SessionLocal
from src.flows.business_hours import BusinessHours
from src.flows.faq_journey import handle_simulated_turn
from src.integrations.appointments import AppointmentService
from src.integrations.orders import OrderLookup


class QueueUnavailableError(RuntimeError):
    """Raised when an event cannot be published to the message broker."""


def enqueue_webhook_event(event_id: str) -> None:
    try:
        process_webhook_event.delay(event_id)
    except OperationalError as error:
        raise QueueUnavailableError("Webhook worker queue is unavailable") from error


@celery_app.task(
    name="src.tasks.process_webhook_event",
    acks_late=True,
    autoretry_for=(SQLAlchemyError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
)  # type: ignore[untyped-decorator]
def process_webhook_event(event_id: str) -> None:
    with SessionLocal() as session:
        settings = get_settings()
        business_name = settings.simulator_business_name.strip()
        _process_webhook_event(
            session,
            event_id,
            simulation_business_name=business_name or None,
            simulation_business_hours=settings.simulator_business_hours,
        )


def _process_webhook_event(
    session: Session,
    event_id: str,
    *,
    simulation_business_name: str | None = None,
    simulation_business_hours: BusinessHours | None = None,
) -> None:
    event_uuid = UUID(event_id)
    event = session.scalar(
        select(WebhookEvent)
        .where(WebhookEvent.id == event_uuid)
        .with_for_update()
    )
    if event is None or event.processing_status == "PROCESSED":
        return

    event.processing_status = "PROCESSING"
    event.attempts += 1
    adapter = SimulatorAdapter()
    inbound_messages = adapter.parse_inbound(event.raw_payload)
    for inbound in inbound_messages:
        existing_message = session.scalar(
            select(Message).where(Message.wamid == inbound.message_id)
        )
        if existing_message is not None:
            continue

        contact = _get_or_create_contact(session, inbound.sender)
        message_at = datetime.fromtimestamp(inbound.timestamp, UTC)
        conversation = _active_conversation(session, contact, message_at)
        is_first_contact = conversation is None
        if conversation is None:
            conversation = Conversation(
                contact=contact,
                state="menu",
                status="BOT",
                session_expires_at=message_at + timedelta(minutes=30),
                window_expires_at=message_at + timedelta(hours=24),
            )
            session.add(conversation)
            session.flush()
        else:
            conversation.session_expires_at = _later(
                conversation.session_expires_at,
                message_at + timedelta(minutes=30),
            )
            conversation.window_expires_at = _later(
                conversation.window_expires_at,
                message_at + timedelta(hours=24),
            )

        content = {
            key: value
            for key, value in {
                "text": inbound.text,
                "selection_id": inbound.selection_id,
                "selection_title": inbound.selection_title,
                "media_id": inbound.media_id,
            }.items()
            if value is not None
        }
        session.add(
            Message(
                conversation_id=conversation.id,
                wamid=inbound.message_id,
                direction="INBOUND",
                message_type=inbound.message_type,
                content=content,
                delivery_status="RECEIVED",
                created_at=message_at,
            )
        )
        text = (inbound.text or "").strip().upper()
        is_opt_out = inbound.message_type == "text" and text in {"PARAR", "SAIR", "CANCELAR"}
        if is_opt_out:
            record_opt_out(session, contact, at=message_at, source=inbound.message_id)
            if conversation.state.startswith("awaiting_marketing:"):
                conversation.state = "faq"

        if simulation_business_name is not None:
            if not simulation_business_name.strip():
                raise ValueError("simulation_business_name must not be empty")
            sent_before = len(adapter.sent_messages)
            if is_opt_out:
                if conversation.status == "BOT":
                    adapter.send_text(
                        inbound.sender,
                        "Seu pedido para bloquear mensagens ativas foi registrado.",
                    )
            elif conversation.status == "BOT":
                articles = list(session.scalars(select(KnowledgeArticle)))

                conversation.state = handle_simulated_turn(
                    adapter,
                    inbound,
                    state=conversation.state,
                    is_first_contact=is_first_contact or conversation.state == "menu",
                    business_name=simulation_business_name,
                    business_hours=simulation_business_hours,
                    articles=articles,
                    orders=OrderLookup(session),
                    appointments=AppointmentService(session),
                    contact_id=contact.id,
                    confirm_marketing=partial(
                        _confirm_marketing, session, contact, message_at, inbound.message_id
                    ),
                )
            for outgoing in adapter.sent_messages[sent_before:]:
                session.add(
                    Message(
                        conversation_id=conversation.id,
                        direction="OUTBOUND",
                        message_type=outgoing.message_type,
                        content=outgoing.payload,
                        delivery_status="SIMULATED",
                    )
                )

    _update_delivery_statuses(session, event.raw_payload)
    event.processing_status = "PROCESSED"
    event.processed_at = datetime.now(UTC)
    event.last_error = None
    session.commit()


def _confirm_marketing(
    session: Session, contact: Contact, message_at: datetime, message_id: str
) -> bool:
    try:
        record_marketing_opt_in(session, contact, at=message_at, source=message_id)
    except StaleOptInError:
        return False
    return True


def _get_or_create_contact(session: Session, wa_id: str) -> Contact:
    existing = session.scalar(
        select(Contact).where(Contact.wa_id == wa_id).with_for_update()
    )
    if existing is not None:
        return existing

    values: dict[str, Any] = {"wa_id": wa_id}
    dialect = session.get_bind().dialect.name
    statement: Any
    if dialect == "postgresql":
        statement = postgresql_insert(Contact).values(**values).on_conflict_do_nothing(
            index_elements=[Contact.wa_id]
        )
    elif dialect == "sqlite":
        statement = sqlite_insert(Contact).values(**values).on_conflict_do_nothing(
            index_elements=[Contact.wa_id]
        )
    else:
        contact = Contact(**values)
        session.add(contact)
        session.flush()
        return contact

    session.execute(statement)
    inserted_contact = session.scalar(
        select(Contact).where(Contact.wa_id == wa_id).with_for_update()
    )
    if inserted_contact is None:
        raise RuntimeError("Contact insert completed without a matching row")
    return inserted_contact


def _active_conversation(
    session: Session, contact: Contact, message_at: datetime
) -> Conversation | None:
    conversation = session.scalar(
        select(Conversation)
        .where(
            Conversation.contact_id == contact.id,
            Conversation.status != "CLOSED",
            or_(
                Conversation.status == "HUMAN",
                Conversation.session_expires_at.is_(None),
                Conversation.session_expires_at > message_at,
            ),
        )
        .order_by(Conversation.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    return conversation


def _later(current: datetime | None, candidate: datetime) -> datetime:
    if current is None:
        return candidate
    normalized_current = (
        current.replace(tzinfo=UTC) if current.tzinfo is None else current
    )
    return max(normalized_current, candidate)


def _update_delivery_statuses(session: Session, payload: dict[str, Any]) -> None:
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for status in value.get("statuses", []):
                message_id = status.get("id")
                delivery_status = status.get("status")
                if not isinstance(message_id, str) or not isinstance(delivery_status, str):
                    continue
                message = session.scalar(select(Message).where(Message.wamid == message_id))
                if message is not None and message.direction == "OUTBOUND":
                    message.delivery_status = delivery_status.upper()
