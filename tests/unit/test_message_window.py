from datetime import UTC, datetime, timedelta

import pytest

from src.flows.message_policy import (
    ApprovedTemplate,
    MessagePolicyError,
    authorize_message,
)

NOW = datetime(2030, 1, 2, 12, 0, tzinfo=UTC)
TEMPLATES = {
    ("aviso", "pt_BR"): ApprovedTemplate(category="utility"),
    ("oferta", "pt_BR"): ApprovedTemplate(category="marketing"),
}


def test_free_message_allowed_before_but_not_at_24_hour_boundary() -> None:
    authorize_message(
        kind="text",
        now=NOW,
        last_customer_message_at=NOW - timedelta(hours=24) + timedelta(microseconds=1),
        proactive=False,
        active_consent=False,
        approved_templates=TEMPLATES,
    )
    with pytest.raises(MessagePolicyError, match="window"):
        authorize_message(
            kind="text",
            now=NOW,
            last_customer_message_at=NOW - timedelta(hours=24),
            proactive=False,
            active_consent=True,
            approved_templates=TEMPLATES,
        )


@pytest.mark.parametrize("kind", ["text", "interactive"])
def test_unknown_window_rejects_free_messages(kind: str) -> None:
    with pytest.raises(MessagePolicyError, match="window"):
        authorize_message(
            kind=kind,
            now=NOW,
            last_customer_message_at=None,
            proactive=False,
            active_consent=False,
            approved_templates=TEMPLATES,
        )


def test_template_requires_exact_catalog_entry_and_returns_category() -> None:
    result = authorize_message(
        kind="template",
        now=NOW,
        last_customer_message_at=None,
        proactive=False,
        active_consent=False,
        approved_templates=TEMPLATES,
        template_name="aviso",
        template_language="pt_BR",
    )
    assert result.category == "utility"
    with pytest.raises(MessagePolicyError, match="approved"):
        authorize_message(
            kind="template",
            now=NOW,
            last_customer_message_at=None,
            proactive=False,
            active_consent=True,
            approved_templates=TEMPLATES,
            template_name="aviso",
            template_language="en_US",
        )


@pytest.mark.parametrize(
    ("kind", "proactive", "template_name"),
    [("text", True, None), ("template", True, "aviso"), ("template", False, "oferta")],
)
def test_active_or_marketing_message_requires_consent(
    kind: str, proactive: bool, template_name: str | None
) -> None:
    with pytest.raises(MessagePolicyError, match="consent"):
        authorize_message(
            kind=kind,
            now=NOW,
            last_customer_message_at=NOW,
            proactive=proactive,
            active_consent=False,
            approved_templates=TEMPLATES,
            template_name=template_name,
            template_language="pt_BR" if template_name else None,
        )


def test_consent_does_not_override_expired_window() -> None:
    with pytest.raises(MessagePolicyError, match="window"):
        authorize_message(
            kind="text",
            now=NOW,
            last_customer_message_at=NOW - timedelta(days=2),
            proactive=True,
            active_consent=True,
            approved_templates=TEMPLATES,
        )


def test_authorized_proactive_marketing_template_outside_window() -> None:
    result = authorize_message(
        kind="template",
        now=NOW,
        last_customer_message_at=None,
        proactive=True,
        active_consent=True,
        approved_templates=TEMPLATES,
        template_name="oferta",
        template_language="pt_BR",
    )
    assert result.category == "marketing"


@pytest.mark.parametrize("kind", ["text", "interactive"])
def test_customer_initiated_reply_does_not_require_marketing_opt_in(kind: str) -> None:
    result = authorize_message(
        kind=kind,
        now=NOW,
        last_customer_message_at=NOW - timedelta(hours=1),
        proactive=False,
        active_consent=False,
        approved_templates=TEMPLATES,
    )
    assert result.category is None


@pytest.mark.parametrize(
    ("now", "inbound"),
    [
        (NOW.replace(tzinfo=None), NOW),
        (NOW, NOW.replace(tzinfo=None)),
        (NOW, NOW + timedelta(seconds=1)),
    ],
)
def test_invalid_timestamps_are_rejected(now: datetime, inbound: datetime) -> None:
    with pytest.raises(MessagePolicyError):
        authorize_message(
            kind="text",
            now=now,
            last_customer_message_at=inbound,
            proactive=False,
            active_consent=False,
            approved_templates=TEMPLATES,
        )


def test_unknown_kind_and_invalid_template_category_are_rejected() -> None:
    with pytest.raises(MessagePolicyError):
        authorize_message(
            kind="unknown",
            now=NOW,
            last_customer_message_at=NOW,
            proactive=False,
            active_consent=True,
            approved_templates=TEMPLATES,
        )
    with pytest.raises(ValueError):
        ApprovedTemplate(category="not-a-category")
