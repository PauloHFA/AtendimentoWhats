from datetime import UTC, datetime, timedelta

import pytest

from src.flows.state_machine import ConversationStateMachine, ConversationStatus

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def test_new_conversation_has_configured_expiry() -> None:
    machine = ConversationStateMachine(session_ttl=timedelta(minutes=30))

    state = machine.start("conversation-1", at=NOW)

    assert state.status is ConversationStatus.BOT
    assert state.expires_at == NOW + timedelta(minutes=30)
    assert not machine.is_expired(state, at=NOW)


def test_understood_turn_resets_consecutive_failures_and_refreshes_expiry() -> None:
    machine = ConversationStateMachine(session_ttl=timedelta(minutes=30))
    state = machine.start("conversation-1", at=NOW)
    state = machine.record_unrecognized(state, at=NOW).state
    state = machine.record_understood(state, at=NOW + timedelta(minutes=5))

    assert state.consecutive_unrecognized == 0
    assert state.expires_at == NOW + timedelta(minutes=35)


def test_second_unrecognized_turn_offers_human_without_forcing_handoff() -> None:
    machine = ConversationStateMachine(session_ttl=timedelta(minutes=30))
    state = machine.start("conversation-1", at=NOW)

    first = machine.record_unrecognized(state, at=NOW)
    second = machine.record_unrecognized(first.state, at=NOW + timedelta(seconds=1))

    assert not first.offer_handoff
    assert second.offer_handoff
    assert second.state.status is ConversationStatus.BOT


def test_human_can_take_over_and_return_control_to_bot() -> None:
    machine = ConversationStateMachine(session_ttl=timedelta(minutes=30))
    state = machine.start("conversation-1", at=NOW)

    human_state = machine.request_human(state, at=NOW)
    returned_state = machine.return_to_bot(human_state, at=NOW + timedelta(minutes=5))

    assert human_state.status is ConversationStatus.HUMAN
    assert returned_state.status is ConversationStatus.BOT
    assert returned_state.expires_at == NOW + timedelta(minutes=35)


def test_human_conversations_reject_bot_turns() -> None:
    machine = ConversationStateMachine(session_ttl=timedelta(minutes=30))
    state = machine.start("conversation-1", at=NOW)
    human_state = machine.request_human(state, at=NOW)

    with pytest.raises(ValueError, match="bot cannot process"):
        machine.record_understood(human_state, at=NOW)


def test_closed_conversations_reject_handoff() -> None:
    machine = ConversationStateMachine(session_ttl=timedelta(minutes=30))
    state = machine.start("conversation-1", at=NOW)
    closed_state = machine.close(state, at=NOW)

    with pytest.raises(ValueError, match="closed conversation"):
        machine.request_human(closed_state, at=NOW)


def test_conversation_expires_after_configured_ttl() -> None:
    machine = ConversationStateMachine(session_ttl=timedelta(minutes=30))
    state = machine.start("conversation-1", at=NOW)

    assert machine.is_expired(state, at=NOW + timedelta(minutes=30))
