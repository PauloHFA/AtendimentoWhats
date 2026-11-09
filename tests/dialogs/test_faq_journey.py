from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.db.models import (
    Base,
    ConsentEvent,
    Contact,
    Conversation,
    KnowledgeArticle,
    Message,
    SimulatedOrder,
    WebhookEvent,
)
from src.tasks import _process_webhook_event


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def send(
    session: Session,
    message_id: str,
    text: str,
    *,
    selection: str | None = None,
    simulate: bool = True,
    timestamp: int = 1794142800,
) -> None:
    message: dict[str, object] = {
        "id": message_id,
        "from": "15550001111",
        "timestamp": str(timestamp),
        "type": "text",
        "text": {"body": text},
    }
    if selection is not None:
        message["type"] = "interactive"
        message.pop("text")
        message["interactive"] = {"list_reply": {"id": selection, "title": text}}
    event = WebhookEvent(
        raw_payload={
            "entry": [
                {"changes": [{"field": "messages", "value": {"messages": [message]}}]}
            ]
        }
    )
    session.add(event)
    session.commit()
    _process_webhook_event(
        session, str(event.id), simulation_business_name="Loja Exemplo" if simulate else None
    )
    _process_webhook_event(
        session, str(event.id), simulation_business_name="Loja Exemplo" if simulate else None
    )


def outbound(session: Session) -> list[Message]:
    return list(
        session.scalars(
            select(Message).where(Message.direction == "OUTBOUND").order_by(Message.created_at)
        )
    )


def test_golden_dialog_greeting_consent_and_grounded_faq(session: Session) -> None:
    session.add(
        KnowledgeArticle(
            title="Horários de atendimento",
            content="Atendemos das 9h às 18h.",
            tags=["horário", "atendimento"],
        )
    )
    session.commit()
    send(session, "wamid.1", "Oi")
    messages = outbound(session)
    assert len(messages) == 2
    assert "assistente automatizado" in messages[0].content["text"]
    assert messages[1].message_type == "interactive"
    assert all(message.delivery_status == "SIMULATED" for message in messages)

    send(session, "wamid.2", "Qual é o horário de atendimento?")
    assert "ACEITO" in outbound(session)[-1].content["text"]
    send(session, "wamid.3", "ACEITO", selection="consent_yes")
    assert "PEDIDO" in outbound(session)[-1].content["text"]
    send(session, "wamid.4", "Qual é o horário de atendimento?")
    assert outbound(session)[-1].content["text"] == (
        "Atendemos das 9h às 18h.\n\nFonte: Horários de atendimento"
    )
    assert len(outbound(session)) == 5


@pytest.mark.parametrize("question", ["Aceitam cartão?", "Qual é a capital da França?"])
def test_no_answer_offers_human_without_inventing(
    session: Session, question: str
) -> None:
    send(session, "wamid.1", "Oi")
    send(session, "wamid.2", "ACEITO", selection="consent_yes")
    send(session, "wamid.3", question)
    message = outbound(session)[-1]
    assert message.message_type == "interactive"
    assert "não encontrei" in message.content["body"].lower()
    assert message.content["action"]["buttons"][0]["reply"]["id"] == "human_handoff"


def test_human_request_is_honest_about_unavailable_handoff(session: Session) -> None:
    send(session, "wamid.1", "Oi")
    send(session, "wamid.2", "Falar com pessoa", selection="human_handoff")
    assert "não está disponível" in outbound(session)[-1].content["text"]
    assert session.scalar(select(Conversation)).status == "BOT"


def test_worker_is_silent_when_simulation_is_disabled(session: Session) -> None:
    send(session, "wamid.1", "Oi", simulate=False)
    assert outbound(session) == []


def test_human_owned_conversation_never_sends_bot_response(session: Session) -> None:
    send(session, "wamid.1", "Oi")
    conversation = session.scalar(select(Conversation))
    assert conversation is not None
    conversation.status = "HUMAN"
    session.commit()
    send(session, "wamid.2", "Qual o horário?")
    assert len(outbound(session)) == 2


def test_human_request_is_available_on_first_turn(session: Session) -> None:
    send(session, "wamid.1", "falar com atendente")
    assert "não está disponível" in outbound(session)[-1].content["text"]


@pytest.mark.parametrize("word", ["PARAR", "sair", "Cancelar"])
def test_opt_out_is_recorded_before_consent(session: Session, word: str) -> None:
    send(session, "wamid.1", word)
    contact = session.scalar(select(Contact))
    assert contact is not None
    assert contact.opt_out_at is not None
    assert not contact.marketing_consent
    assert "bloquear mensagens ativas" in outbound(session)[-1].content["text"]
    send(session, "wamid.2", "Oi")
    assert "assistente automatizado" in outbound(session)[-2].content["text"]


def test_enabling_simulator_for_existing_conversation_starts_journey(session: Session) -> None:
    send(session, "wamid.1", "Oi", simulate=False)
    send(session, "wamid.2", "Olá")
    assert "assistente automatizado" in outbound(session)[0].content["text"]


def test_opt_out_during_human_ownership_does_not_send_bot_message(session: Session) -> None:
    send(session, "wamid.1", "Oi")
    conversation = session.scalar(select(Conversation))
    assert conversation is not None
    conversation.status = "HUMAN"
    session.commit()
    send(session, "wamid.2", "PARAR")
    contact = session.scalar(select(Contact))
    assert contact is not None and contact.opt_out_at is not None
    assert len(outbound(session)) == 2


@pytest.mark.parametrize("word", ["PARAR", " sair ", "Cancelar"])
def test_opt_out_is_recorded_even_when_simulator_disabled(session: Session, word: str) -> None:
    send(session, "wamid.1", word, simulate=False)
    contact = session.scalar(select(Contact))
    assert contact is not None
    assert contact.opt_out_at is not None
    assert contact.marketing_consent is False
    assert outbound(session) == []
    events = session.scalars(select(ConsentEvent)).all()
    assert len(events) == 1
    assert events[0].action == "OPT_OUT"
    assert events[0].source == "wamid.1"


def test_opt_out_revokes_existing_marketing_consent(session: Session) -> None:
    contact = Contact(
        wa_id="15550001111",
        marketing_consent=True,
    )
    session.add(contact)
    session.commit()
    send(session, "wamid.1", "PARAR", simulate=False)
    session.refresh(contact)
    assert not contact.marketing_consent
    assert contact.opt_out_at is not None


def test_marketing_opt_in_requires_separate_explicit_confirmation(session: Session) -> None:
    send(session, "wamid.1", "Oi")
    send(session, "wamid.2", "Aceito", selection="consent_yes")
    contact = session.scalar(select(Contact))
    assert contact is not None and not contact.marketing_consent
    send(session, "wamid.3", "marketing")
    assert "mensagens de marketing" in outbound(session)[-1].content["body"].lower()
    send(session, "wamid.4", "Sim", selection="marketing_yes", timestamp=1794142801)
    session.refresh(contact)
    assert contact.marketing_consent
    events = session.scalars(select(ConsentEvent)).all()
    assert [(event.action, event.source) for event in events] == [("OPT_IN", "wamid.4")]


def test_marketing_decline_and_unsolicited_confirmation_never_grant(session: Session) -> None:
    send(session, "wamid.1", "Oi")
    send(session, "wamid.2", "Aceito", selection="consent_yes")
    send(session, "wamid.3", "Sim", selection="marketing_yes")
    send(session, "wamid.4", "marketing")
    send(session, "wamid.5", "Não", selection="marketing_no")
    contact = session.scalar(select(Contact))
    assert contact is not None and not contact.marketing_consent
    assert session.scalars(select(ConsentEvent)).all() == []


def test_opt_out_cancels_pending_prompt_and_stale_reply_cannot_reenable(session: Session) -> None:
    send(session, "wamid.1", "Oi")
    send(session, "wamid.2", "Aceito", selection="consent_yes")
    send(session, "wamid.3", "marketing")
    send(session, "wamid.4", "PARAR", timestamp=1794142802)
    send(session, "wamid.5", "Sim", selection="marketing_yes", timestamp=1794142801)
    contact = session.scalar(select(Contact))
    assert contact is not None and not contact.marketing_consent
    assert [event.action for event in session.scalars(select(ConsentEvent)).all()] == ["OPT_OUT"]


def test_stale_confirmation_after_new_prompt_is_refused(session: Session) -> None:
    send(session, "wamid.1", "Oi")
    send(session, "wamid.2", "Aceito", selection="consent_yes")
    send(session, "wamid.3", "PARAR", timestamp=1794142802)
    send(session, "wamid.4", "marketing", timestamp=1794142803)
    send(session, "wamid.5", "Sim", selection="marketing_yes", timestamp=1794142801)
    contact = session.scalar(select(Contact))
    assert contact is not None and not contact.marketing_consent
    assert "não foi possível" in outbound(session)[-1].content["text"].lower()
    assert [event.action for event in session.scalars(select(ConsentEvent)).all()] == ["OPT_OUT"]


def test_confirmation_older_than_prompt_is_rejected_without_prior_opt_out(session: Session) -> None:
    send(session, "wamid.1", "Oi")
    send(session, "wamid.2", "Aceito", selection="consent_yes")
    send(session, "wamid.3", "marketing", timestamp=1794142805)
    send(session, "wamid.4", "Sim", selection="marketing_yes", timestamp=1794142804)
    contact = session.scalar(select(Contact))
    assert contact is not None and not contact.marketing_consent
    assert "não foi possível" in outbound(session)[-1].content["text"].lower()


def test_order_dialog_validates_number_and_returns_simulated_status(session: Session) -> None:
    send(session, "wamid.1", "Oi")
    contact = session.scalar(select(Contact))
    assert contact is not None
    session.add(
        SimulatedOrder(
            number="001234",
            contact_id=contact.id,
            status="Em transporte",
            expected_date=date(2026, 11, 12),
        )
    )
    session.commit()
    send(session, "wamid.2", "Aceito", selection="consent_yes")
    send(session, "wamid.3", "pedido")
    assert "número" in outbound(session)[-1].content["text"]
    send(session, "wamid.4", "123")
    assert "inválido" in outbound(session)[-1].content["text"]
    send(session, "wamid.5", "001234")
    assert outbound(session)[-1].content["text"] == (
        "Pedido 001234: Em transporte. Previsão: 12/11/2026."
    )


def test_order_for_another_contact_is_not_disclosed(session: Session) -> None:
    send(session, "wamid.1", "Oi")
    other = Contact(wa_id="15550002222")
    session.add(other)
    session.flush()
    session.add(SimulatedOrder(number="001234", contact_id=other.id, status="Segredo"))
    session.commit()
    send(session, "wamid.2", "Aceito", selection="consent_yes")
    send(session, "wamid.3", "pedido")
    send(session, "wamid.4", "001234")
    assert "não encontrei" in outbound(session)[-1].content["text"].lower()
    assert "Segredo" not in outbound(session)[-1].content["text"]


def test_simulated_response_and_inbound_rollback_together_on_flow_error(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    send(session, "wamid.1", "Oi")
    event = WebhookEvent(
        raw_payload={
            "entry": [
                {
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messages": [
                                    {
                                        "id": "wamid.failed",
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
        }
    )
    session.add(event)
    session.commit()

    def fail(*args: object, **kwargs: object) -> str:
        raise RuntimeError("erro simulado")

    monkeypatch.setattr("src.tasks.handle_simulated_turn", fail)
    with pytest.raises(RuntimeError, match="erro simulado"):
        _process_webhook_event(session, str(event.id), simulation_business_name="Loja Exemplo")
    session.rollback()

    assert session.scalar(select(Message).where(Message.wamid == "wamid.failed")) is None
    assert len(outbound(session)) == 2
    assert session.get(WebhookEvent, event.id).processing_status == "PENDING"
