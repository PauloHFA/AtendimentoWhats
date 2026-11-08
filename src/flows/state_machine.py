from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class ConversationStatus(StrEnum):
    BOT = "BOT"
    HUMAN = "HUMAN"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class ConversationState:
    conversation_id: str
    status: ConversationStatus
    step: str
    consecutive_unrecognized: int
    expires_at: datetime


@dataclass(frozen=True)
class TurnOutcome:
    state: ConversationState
    offer_handoff: bool


class ConversationStateMachine:
    def __init__(
        self,
        session_ttl: timedelta,
        max_unrecognized: int = 2,
    ) -> None:
        if session_ttl <= timedelta(0):
            raise ValueError("session_ttl must be positive")
        if max_unrecognized < 1:
            raise ValueError("max_unrecognized must be positive")
        self._session_ttl = session_ttl
        self._max_unrecognized = max_unrecognized

    def start(
        self, conversation_id: str, at: datetime | None = None
    ) -> ConversationState:
        if not conversation_id.strip():
            raise ValueError("conversation_id must not be empty")
        now = self._now(at)
        return ConversationState(
            conversation_id=conversation_id,
            status=ConversationStatus.BOT,
            step="menu",
            consecutive_unrecognized=0,
            expires_at=now + self._session_ttl,
        )

    def record_understood(
        self, state: ConversationState, at: datetime | None = None
    ) -> ConversationState:
        self._require_bot(state)
        return replace(
            state,
            consecutive_unrecognized=0,
            expires_at=self._now(at) + self._session_ttl,
        )

    def record_unrecognized(
        self, state: ConversationState, at: datetime | None = None
    ) -> TurnOutcome:
        self._require_bot(state)
        failures = state.consecutive_unrecognized + 1
        updated_state = replace(
            state,
            consecutive_unrecognized=failures,
            expires_at=self._now(at) + self._session_ttl,
        )
        return TurnOutcome(
            state=updated_state,
            offer_handoff=failures >= self._max_unrecognized,
        )

    def request_human(
        self, state: ConversationState, at: datetime | None = None
    ) -> ConversationState:
        if state.status is ConversationStatus.CLOSED:
            raise ValueError("closed conversation cannot be handed off")
        return replace(
            state,
            status=ConversationStatus.HUMAN,
            expires_at=self._now(at) + self._session_ttl,
        )

    def return_to_bot(
        self, state: ConversationState, at: datetime | None = None
    ) -> ConversationState:
        if state.status is not ConversationStatus.HUMAN:
            raise ValueError("only a human-owned conversation can return to the bot")
        return replace(
            state,
            status=ConversationStatus.BOT,
            consecutive_unrecognized=0,
            expires_at=self._now(at) + self._session_ttl,
        )

    def close(
        self, state: ConversationState, at: datetime | None = None
    ) -> ConversationState:
        return replace(state, status=ConversationStatus.CLOSED, expires_at=self._now(at))

    def is_expired(
        self, state: ConversationState, at: datetime | None = None
    ) -> bool:
        return self._now(at) >= state.expires_at

    @staticmethod
    def _now(at: datetime | None) -> datetime:
        value = at if at is not None else datetime.now(UTC)
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must include a timezone")
        return value

    @staticmethod
    def _require_bot(state: ConversationState) -> None:
        if state.status is not ConversationStatus.BOT:
            raise ValueError("bot cannot process a conversation it does not own")
