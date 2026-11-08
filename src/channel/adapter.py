from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

MessageType = Literal["text", "button", "interactive", "image", "audio", "document", "unsupported"]
OutboundType = Literal["text", "interactive", "template"]
_MEDIA_TYPES: dict[str, Literal["image", "audio", "document"]] = {
    "image": "image",
    "audio": "audio",
    "document": "document",
}


@dataclass(frozen=True)
class InboundMessage:
    message_id: str
    sender: str
    timestamp: int
    message_type: MessageType
    text: str | None = None
    selection_id: str | None = None
    selection_title: str | None = None
    media_id: str | None = None


@dataclass(frozen=True)
class OutboundMessage:
    recipient: str
    message_type: OutboundType
    payload: dict[str, object]


class ChannelAdapter(Protocol):
    def parse_inbound(self, payload: Mapping[str, object]) -> list[InboundMessage]: ...

    def send_text(self, recipient: str, text: str) -> OutboundMessage: ...

    def send_interactive(
        self, recipient: str, interactive: Mapping[str, object]
    ) -> OutboundMessage: ...

    def send_template(
        self,
        recipient: str,
        name: str,
        language: str = "pt_BR",
        components: list[Mapping[str, object]] | None = None,
    ) -> OutboundMessage: ...

    def mark_read(self, message_id: str) -> None: ...


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _items(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return value


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _parse_message(message: Mapping[str, object]) -> InboundMessage:
    message_id = _required_string(message.get("id"), "message.id")
    sender = _required_string(message.get("from"), "message.from")
    raw_timestamp = message.get("timestamp")
    if isinstance(raw_timestamp, int):
        timestamp = raw_timestamp
    elif isinstance(raw_timestamp, str):
        try:
            timestamp = int(raw_timestamp)
        except ValueError as error:
            raise ValueError("message.timestamp must be an integer") from error
    else:
        raise ValueError("message.timestamp must be an integer")

    raw_type = _required_string(message.get("type"), "message.type")
    if raw_type == "text":
        text = _mapping(message.get("text"), "message.text")
        return InboundMessage(
            message_id,
            sender,
            timestamp,
            "text",
            text=_required_string(text.get("body"), "text.body"),
        )

    if raw_type == "button":
        button = _mapping(message.get("button"), "message.button")
        return InboundMessage(
            message_id,
            sender,
            timestamp,
            "button",
            text=_optional_string(button.get("text")),
            selection_id=_optional_string(button.get("payload")),
        )

    if raw_type == "interactive":
        interactive = _mapping(message.get("interactive"), "message.interactive")
        for reply_type in ("button_reply", "list_reply"):
            reply = interactive.get(reply_type)
            if reply is not None:
                reply_data = _mapping(reply, f"interactive.{reply_type}")
                return InboundMessage(
                    message_id,
                    sender,
                    timestamp,
                    "interactive",
                    selection_id=_optional_string(reply_data.get("id")),
                    selection_title=_optional_string(reply_data.get("title")),
                )
        return InboundMessage(message_id, sender, timestamp, "interactive")

    media_type = _MEDIA_TYPES.get(raw_type)
    if media_type is not None:
        media = _mapping(message.get(media_type), f"message.{media_type}")
        return InboundMessage(
            message_id,
            sender,
            timestamp,
            media_type,
            media_id=_optional_string(media.get("id")),
        )

    return InboundMessage(message_id, sender, timestamp, "unsupported")
