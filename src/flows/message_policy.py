from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

_CATEGORIES = frozenset({"marketing", "utility", "authentication"})
_FREE_MESSAGE_TYPES = frozenset({"text", "interactive"})


class MessagePolicyError(ValueError):
    """The proposed outbound message does not satisfy the messaging policy."""


@dataclass(frozen=True)
class ApprovedTemplate:
    category: str

    def __post_init__(self) -> None:
        if self.category not in _CATEGORIES:
            raise ValueError(f"Unknown template category: {self.category}")


@dataclass(frozen=True)
class AuthorizedMessage:
    category: str | None


def authorize_message(
    *,
    kind: str,
    now: datetime,
    last_customer_message_at: datetime | None,
    proactive: bool,
    active_consent: bool,
    approved_templates: Mapping[tuple[str, str], ApprovedTemplate],
    template_name: str | None = None,
    template_language: str | None = None,
) -> AuthorizedMessage:
    if now.tzinfo is None or now.utcoffset() is None:
        raise MessagePolicyError("current time must include a timezone")
    if last_customer_message_at is not None:
        if (
            last_customer_message_at.tzinfo is None
            or last_customer_message_at.utcoffset() is None
        ):
            raise MessagePolicyError("customer message time must include a timezone")
        if last_customer_message_at > now:
            raise MessagePolicyError("customer message time cannot be in the future")

    if kind in _FREE_MESSAGE_TYPES:
        if template_name is not None or template_language is not None:
            raise MessagePolicyError("template details are invalid for a free message")
        if (
            last_customer_message_at is None
            or now - last_customer_message_at >= timedelta(hours=24)
        ):
            raise MessagePolicyError("free message is outside the customer service window")
        category = None
    elif kind == "template":
        if not template_name or not template_language:
            raise MessagePolicyError("approved template name and language are required")
        template = approved_templates.get((template_name, template_language))
        if template is None:
            raise MessagePolicyError("template is not approved for this name and language")
        category = template.category
    else:
        raise MessagePolicyError(f"unsupported outbound message type: {kind}")

    if (proactive or category == "marketing") and not active_consent:
        raise MessagePolicyError("active message requires explicit consent")
    return AuthorizedMessage(category=category)
