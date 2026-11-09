from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.celery_app import celery_app
from src.db.models import Base, Contact, Conversation, Message, WebhookEvent
from src.tasks import _process_webhook_event, process_webhook_event


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_schema_creates_all_domain_tables(session: Session) -> None:
    assert set(Base.metadata.tables) == {
        "contacts",
        "consent_events",
        "conversations",
        "messages",
        "simulated_orders",
        "tickets",
        "appointments",
        "knowledge_articles",
        "webhook_events",
        "usage_counters",
        "usage_records",
    }


def test_contact_conversation_and_message_relationships(session: Session) -> None:
    contact = Contact(wa_id="15550001111", name="Teste")
    conversation = Conversation(contact=contact)
    message = Message(
        conversation=conversation,
        wamid="wamid.test-1",
        direction="INBOUND",
        message_type="text",
        content={"text": "Oi"},
    )
    session.add(message)
    session.commit()

    stored = session.scalar(select(Message).where(Message.wamid == "wamid.test-1"))

    assert stored is not None
    assert stored.conversation.contact.wa_id == "15550001111"
    assert stored.delivery_status == "PENDING"


def test_contact_wa_id_is_unique(session: Session) -> None:
    session.add_all([Contact(wa_id="15550001111"), Contact(wa_id="15550001111")])

    with pytest.raises(IntegrityError):
        session.commit()


def test_message_wamid_is_unique(session: Session) -> None:
    contact = Contact(wa_id="15550001111")
    conversation = Conversation(contact=contact)
    session.add_all(
        [
            Message(
                conversation=conversation,
                wamid="wamid.duplicate",
                direction="INBOUND",
                message_type="text",
                content={"text": "one"},
            ),
            Message(
                conversation=conversation,
                wamid="wamid.duplicate",
                direction="INBOUND",
                message_type="text",
                content={"text": "two"},
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_webhook_event_persists_raw_payload_and_processing_state(session: Session) -> None:
    event = WebhookEvent(
        wamid="wamid.event-1",
        raw_payload={"entry": [{"id": "test"}]},
    )
    session.add(event)
    session.commit()

    stored = session.scalar(select(WebhookEvent).where(WebhookEvent.wamid == "wamid.event-1"))

    assert stored is not None
    assert stored.raw_payload == {"entry": [{"id": "test"}]}
    assert stored.processing_status == "PENDING"
    assert stored.received_at is not None
    received_at = stored.received_at.replace(tzinfo=UTC)
    assert received_at <= datetime.now(UTC) + timedelta(seconds=1)
    assert stored.processed_at is None


def test_ids_are_uuids(session: Session) -> None:
    contact = Contact(wa_id="15550001111")
    session.add(contact)
    session.commit()

    assert isinstance(contact.id, type(uuid4()))


def test_worker_persists_inbound_message_and_is_idempotent(session: Session) -> None:
    event = WebhookEvent(
        wamid="wamid.worker-test",
        raw_payload={
            "entry": [
                {
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messages": [
                                    {
                                        "id": "wamid.worker-test",
                                        "from": "15550001111",
                                        "timestamp": "1794142800",
                                        "type": "text",
                                        "text": {"body": "Oi"},
                                    }
                                ]
                            },
                        }
                    ]
                }
            ]
        },
    )
    session.add(event)
    session.commit()
    event_id = str(event.id)

    _process_webhook_event(session, event_id)
    _process_webhook_event(session, event_id)

    assert session.scalar(select(func.count()).select_from(Contact)) == 1
    assert session.scalar(select(func.count()).select_from(Conversation)) == 1
    assert session.scalar(select(func.count()).select_from(Message)) == 1
    stored_message = session.scalar(select(Message))
    stored_event = session.get(WebhookEvent, event.id)
    assert stored_message is not None
    assert stored_message.content == {"text": "Oi"}
    assert stored_event is not None
    assert stored_event.processing_status == "PROCESSED"
    assert stored_event.attempts == 1


def test_worker_applies_delivery_status_for_known_outbound_message(session: Session) -> None:
    contact = Contact(wa_id="15550002222")
    conversation = Conversation(contact=contact)
    outbound = Message(
        conversation=conversation,
        wamid="wamid.outbound",
        direction="OUTBOUND",
        message_type="text",
        content={"text": "Olá"},
        delivery_status="SENT",
    )
    event = WebhookEvent(
        wamid="wamid.outbound",
        dedupe_key="status:wamid.outbound:read:1794142800",
        raw_payload={
            "entry": [
                {
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "statuses": [
                                    {
                                        "id": "wamid.outbound",
                                        "status": "read",
                                        "timestamp": "1794142800",
                                    }
                                ]
                            },
                        }
                    ]
                }
            ]
        },
    )
    session.add_all([outbound, event])
    session.commit()

    _process_webhook_event(session, str(event.id))

    assert outbound.delivery_status == "READ"
    assert event.processing_status == "PROCESSED"


def test_worker_retries_database_errors_with_backoff() -> None:
    assert process_webhook_event.max_retries == 5
    assert process_webhook_event.autoretry_for
    assert "src.tasks" in celery_app.conf.include
