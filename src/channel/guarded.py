from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from src.channel.adapter import ChannelAdapter, InboundMessage, OutboundMessage
from src.flows.message_policy import ApprovedTemplate, authorize_message


@dataclass(frozen=True)
class MessageContext:
    last_customer_message_at: datetime | None
    active_consent: bool


class GuardedChannel(ChannelAdapter):
    def __init__(
        self,
        channel: ChannelAdapter,
        *,
        get_context: Callable[[str], MessageContext],
        now: Callable[[], datetime],
        proactive: bool,
        approved_templates: Mapping[tuple[str, str], ApprovedTemplate],
    ) -> None:
        self._channel = channel
        self._get_context = get_context
        self._now = now
        self._proactive = proactive
        self._approved_templates = approved_templates

    def parse_inbound(self, payload: Mapping[str, object]) -> list[InboundMessage]:
        return self._channel.parse_inbound(payload)

    def send_text(self, recipient: str, text: str) -> OutboundMessage:
        self._authorize(recipient, "text")
        return self._channel.send_text(recipient, text)

    def send_interactive(
        self, recipient: str, interactive: Mapping[str, object]
    ) -> OutboundMessage:
        self._authorize(recipient, "interactive")
        return self._channel.send_interactive(recipient, interactive)

    def send_template(
        self,
        recipient: str,
        name: str,
        language: str = "pt_BR",
        components: list[Mapping[str, object]] | None = None,
    ) -> OutboundMessage:
        self._authorize(recipient, "template", template_name=name, template_language=language)
        return self._channel.send_template(recipient, name, language, components)

    def mark_read(self, message_id: str) -> None:
        self._channel.mark_read(message_id)

    def _authorize(
        self,
        recipient: str,
        kind: str,
        *,
        template_name: str | None = None,
        template_language: str | None = None,
    ) -> None:
        context = self._get_context(recipient)
        authorize_message(
            kind=kind,
            now=self._now(),
            last_customer_message_at=context.last_customer_message_at,
            proactive=self._proactive,
            active_consent=context.active_consent,
            approved_templates=self._approved_templates,
            template_name=template_name,
            template_language=template_language,
        )
