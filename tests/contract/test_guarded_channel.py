from datetime import UTC, datetime, timedelta

import pytest

from src.channel.guarded import GuardedChannel, MessageContext
from src.channel.simulator import SimulatorAdapter
from src.flows.message_policy import ApprovedTemplate, MessagePolicyError

NOW = datetime(2030, 1, 2, 12, 0, tzinfo=UTC)


def test_guarded_channel_rechecks_consent_before_every_active_send() -> None:
    simulator = SimulatorAdapter()
    context = MessageContext(
        last_customer_message_at=NOW - timedelta(minutes=5),
        active_consent=True,
    )
    channel = GuardedChannel(
        simulator,
        get_context=lambda recipient: context,
        now=lambda: NOW,
        proactive=True,
        approved_templates={},
    )

    channel.send_text("15550001111", "Primeira mensagem")
    context = MessageContext(last_customer_message_at=NOW, active_consent=False)
    with pytest.raises(MessagePolicyError, match="consent"):
        channel.send_text("15550001111", "Não deve ser enviada")
    assert [item.payload["text"] for item in simulator.sent_messages] == ["Primeira mensagem"]


def test_guarded_channel_rejects_expired_window_before_delegate() -> None:
    simulator = SimulatorAdapter()
    channel = GuardedChannel(
        simulator,
        get_context=lambda recipient: MessageContext(
            last_customer_message_at=NOW - timedelta(hours=24),
            active_consent=True,
        ),
        now=lambda: NOW,
        proactive=False,
        approved_templates={},
    )
    with pytest.raises(MessagePolicyError, match="window"):
        channel.send_interactive("15550001111", {"type": "button"})
    assert simulator.sent_messages == []


def test_guarded_channel_validates_template_name_language_and_category() -> None:
    simulator = SimulatorAdapter()
    context = MessageContext(last_customer_message_at=None, active_consent=False)
    channel = GuardedChannel(
        simulator,
        get_context=lambda recipient: context,
        now=lambda: NOW,
        proactive=False,
        approved_templates={("oferta", "pt_BR"): ApprovedTemplate(category="marketing")},
    )
    with pytest.raises(MessagePolicyError, match="consent"):
        channel.send_template("15550001111", "oferta")
    context = MessageContext(last_customer_message_at=None, active_consent=True)
    with pytest.raises(MessagePolicyError, match="approved"):
        channel.send_template("15550001111", "oferta", language="en_US")
    message = channel.send_template("15550001111", "oferta")
    assert message.payload == {"name": "oferta", "language": "pt_BR"}
    assert len(simulator.sent_messages) == 1


def test_context_failure_never_delegates() -> None:
    simulator = SimulatorAdapter()

    def unavailable(recipient: str) -> MessageContext:
        raise RuntimeError("context unavailable")

    channel = GuardedChannel(
        simulator, get_context=unavailable, now=lambda: NOW, proactive=False, approved_templates={}
    )
    with pytest.raises(RuntimeError, match="context unavailable"):
        channel.send_text("15550001111", "Mensagem")
    assert simulator.sent_messages == []


def test_guarded_channel_preserves_parsing_and_read_receipts() -> None:
    simulator = SimulatorAdapter()
    channel = GuardedChannel(
        simulator,
        get_context=lambda recipient: MessageContext(None, False),
        now=lambda: NOW,
        proactive=False,
        approved_templates={},
    )
    assert channel.parse_inbound({"entry": []}) == []
    channel.mark_read("wamid.inbound")
    assert simulator.read_message_ids == ["wamid.inbound"]
