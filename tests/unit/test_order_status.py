from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db.models import Base, Contact, SimulatedOrder
from src.integrations.orders import InvalidOrderNumber, OrderLookup


@pytest.mark.parametrize("number", ["", "12", "abcd", "12-34", "１２３４", "1" * 21])
def test_invalid_order_number_never_queries_database(number: str) -> None:
    class NoQuerySession:
        def scalar(self, *args: object) -> None:
            raise AssertionError("database must not be queried for invalid numbers")

    with pytest.raises(InvalidOrderNumber):
        OrderLookup(NoQuerySession()).lookup(uuid4(), number)


def test_lookup_is_scoped_to_contact_and_returns_status_and_date() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        owner = Contact(wa_id="15550001111")
        other = Contact(wa_id="15550002222")
        session.add_all([owner, other])
        session.flush()
        session.add(
            SimulatedOrder(
                number="001234",
                contact_id=owner.id,
                status="Em transporte",
                expected_date=date(2026, 11, 12),
            )
        )
        session.commit()
        lookup = OrderLookup(session)

        result = lookup.lookup(owner.id, " 001234 ")
        assert result is not None
        assert result.number == "001234"
        assert result.status == "Em transporte"
        assert result.expected_date == date(2026, 11, 12)
        assert lookup.lookup(other.id, "001234") is None
        assert lookup.lookup(owner.id, "999999") is None
    engine.dispose()
