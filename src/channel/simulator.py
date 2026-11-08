from __future__ import annotations

from collections.abc import Mapping

from src.channel.adapter import (
    ChannelAdapter,
    InboundMessage,
    OutboundMessage,
    OutboundType,
    _items,
    _mapping,
    _parse_message,
    _required_string,
)


class SimulatorAdapter(ChannelAdapter):
    def __init__(self) -> None:
        self.sent_messages: list[OutboundMessage] = []
        self.read_message_ids: list[str] = []

    def parse_inbound(self, payload: Mapping[str, object]) -> list[InboundMessage]:
        entries = _items(payload.get("entry", []), "entry")
        messages: list[InboundMessage] = []
        for entry_index, entry_value in enumerate(entries):
            entry = _mapping(entry_value, f"entry[{entry_index}]")
            changes = _items(entry.get("changes", []), f"entry[{entry_index}].changes")
            for change_index, change_value in enumerate(changes):
                change = _mapping(change_value, f"changes[{change_index}]")
                if change.get("field") != "messages":
                    continue
                value = _mapping(change.get("value"), "change.value")
                raw_messages = value.get("messages", [])
                if not isinstance(raw_messages, list):
                    raise ValueError("change.value.messages must be an array")
                for message_index, message_value in enumerate(raw_messages):
                    message = _mapping(message_value, f"messages[{message_index}]")
                    messages.append(_parse_message(message))
        return messages

    def send_text(self, recipient: str, text: str) -> OutboundMessage:
        recipient = _required_string(recipient, "recipient")
        text = _required_string(text, "text")
        return self._record(recipient, "text", {"text": text})

    def send_interactive(
        self, recipient: str, interactive: Mapping[str, object]
    ) -> OutboundMessage:
        recipient = _required_string(recipient, "recipient")
        payload = dict(_mapping(interactive, "interactive"))
        if not payload:
            raise ValueError("interactive must not be empty")
        return self._record(recipient, "interactive", payload)

    def send_template(
        self,
        recipient: str,
        name: str,
        language: str = "pt_BR",
        components: list[Mapping[str, object]] | None = None,
    ) -> OutboundMessage:
        recipient = _required_string(recipient, "recipient")
        name = _required_string(name, "template.name")
        language = _required_string(language, "template.language")
        payload: dict[str, object] = {"name": name, "language": language}
        if components is not None:
            payload["components"] = [dict(component) for component in components]
        return self._record(recipient, "template", payload)

    def mark_read(self, message_id: str) -> None:
        self.read_message_ids.append(_required_string(message_id, "message_id"))

    def _record(
        self, recipient: str, message_type: OutboundType, payload: dict[str, object]
    ) -> OutboundMessage:
        message = OutboundMessage(recipient, message_type, payload)
        self.sent_messages.append(message)
        return message
