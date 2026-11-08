import pytest

from src.channel.simulator import SimulatorAdapter
from src.flows.welcome import send_first_contact


def test_first_contact_identifies_bot_requests_consent_and_offers_human() -> None:
    channel = SimulatorAdapter()

    sent = send_first_contact(channel, "15550001111", "Clínica Exemplo")

    assert len(sent) == 2
    assert "assistente automatizado" in sent[0].payload["text"].lower()
    assert "CLÍNICA EXEMPLO" in sent[0].payload["text"].upper()
    assert "ACEITO" in sent[0].payload["text"]
    assert sent[1].message_type == "interactive"
    payload = sent[1].payload
    assert isinstance(payload["action"], dict)
    rows = payload["action"]["sections"][0]["rows"]
    assert any(row["id"] == "consent_yes" for row in rows)
    assert any(row["id"] == "human_handoff" for row in rows)


def test_first_contact_rejects_empty_business_name() -> None:
    channel = SimulatorAdapter()

    with pytest.raises(ValueError, match="business_name"):
        send_first_contact(channel, "15550001111", "  ")
