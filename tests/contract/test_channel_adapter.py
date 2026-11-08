import json
from pathlib import Path

import pytest

from src.channel.adapter import ChannelAdapter
from src.channel.simulator import SimulatorAdapter

PAYLOAD_PATH = Path(__file__).parents[2] / "simulator" / "payloads" / "text-message.json"


def test_simulator_parses_recorded_text_payload() -> None:
    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    adapter: ChannelAdapter = SimulatorAdapter()

    messages = adapter.parse_inbound(payload)

    assert len(messages) == 1
    assert messages[0].message_id == "wamid.test-message-001"
    assert messages[0].sender == "15550001111"
    assert messages[0].text == "Oi"


@pytest.mark.parametrize(
    ("message_type", "content", "expected_type", "expected_selection", "expected_media"),
    [
        ("button", {"text": "Agendar", "payload": "book"}, "button", "book", None),
        (
            "interactive",
            {"button_reply": {"id": "faq", "title": "Perguntas frequentes"}},
            "interactive",
            "faq",
            None,
        ),
        ("image", {"id": "media-1"}, "image", None, "media-1"),
        ("audio", {"id": "media-2"}, "audio", None, "media-2"),
        ("document", {"id": "media-3"}, "document", None, "media-3"),
    ],
)
def test_simulator_parses_supported_message_types(
    message_type: str,
    content: dict[str, object],
    expected_type: str,
    expected_selection: str | None,
    expected_media: str | None,
) -> None:
    adapter = SimulatorAdapter()
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messages": [
                                {
                                    "id": "wamid.test",
                                    "from": "15550001111",
                                    "timestamp": "1731000000",
                                    "type": message_type,
                                    message_type: content,
                                }
                            ]
                        },
                    }
                ]
            }
        ]
    }

    message = adapter.parse_inbound(payload)[0]

    assert message.message_type == expected_type
    assert message.selection_id == expected_selection
    assert message.media_id == expected_media


def test_simulator_ignores_delivery_status_events() -> None:
    adapter = SimulatorAdapter()
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {"statuses": [{"id": "wamid.test", "status": "delivered"}]},
                    }
                ]
            }
        ]
    }

    assert adapter.parse_inbound(payload) == []


def test_simulator_rejects_malformed_message() -> None:
    adapter = SimulatorAdapter()
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {"messages": [{"from": "15550001111"}]},
                    }
                ]
            }
        ]
    }

    with pytest.raises(ValueError, match="message.id"):
        adapter.parse_inbound(payload)


def test_simulator_captures_outgoing_messages_and_read_receipts() -> None:
    adapter = SimulatorAdapter()

    text = adapter.send_text("15550001111", "Olá")
    interactive = adapter.send_interactive("15550001111", {"type": "button"})
    template = adapter.send_template("15550001111", "hello_world")
    adapter.mark_read("wamid.inbound")

    assert text.payload == {"text": "Olá"}
    assert interactive.message_type == "interactive"
    assert template.payload == {"name": "hello_world", "language": "pt_BR"}
    assert [message.message_type for message in adapter.sent_messages] == [
        "text",
        "interactive",
        "template",
    ]
    assert adapter.read_message_ids == ["wamid.inbound"]
