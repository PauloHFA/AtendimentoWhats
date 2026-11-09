from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.sql import Select

from src.db.models import SimulatedOrder

_ORDER_NUMBER = re.compile(r"[0-9]{4,20}\Z")


class InvalidOrderNumber(ValueError):
    """Order number does not match the simulated format."""


class OrderSession(Protocol):
    def scalar(self, statement: Select[SimulatedOrder]) -> SimulatedOrder | None: ...


@dataclass(frozen=True)
class OrderStatus:
    number: str
    status: str
    expected_date: date | None


class OrderLookup:
    def __init__(self, session: OrderSession) -> None:
        self._session = session

    def lookup(self, contact_id: UUID, number: str) -> OrderStatus | None:
        normalized = number.strip()
        if _ORDER_NUMBER.fullmatch(normalized) is None:
            raise InvalidOrderNumber("Order number must have 4 to 20 ASCII digits")
        order = self._session.scalar(
            select(SimulatedOrder).where(
                SimulatedOrder.number == normalized,
                SimulatedOrder.contact_id == contact_id,
            )
        )
        if order is None:
            return None
        return OrderStatus(order.number, order.status, order.expected_date)
