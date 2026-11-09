from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models import Appointment, Base, Contact
from src.integrations.appointments import (
    AppointmentConflict,
    AppointmentService,
    InvalidAppointment,
)

START = datetime(2035, 1, 1, 10, 0, tzinfo=UTC)
SLOT = timedelta(minutes=30)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_booking_availability_lookup_and_cancel_are_contact_scoped(session: Session) -> None:
    alice = Contact(wa_id="15550000001")
    bob = Contact(wa_id="15550000002")
    session.add_all([alice, bob])
    session.flush()
    service = AppointmentService(session)

    booking = service.book(alice.id, "Consulta", START)
    assert booking.status == "BOOKED"
    assert booking.ends_at.replace(tzinfo=UTC) == START + SLOT
    assert service.available("Consulta", START, START + 3 * SLOT) == [
        START + SLOT,
        START + 2 * SLOT,
    ]
    assert [item.id for item in service.list_for_contact(alice.id)] == [booking.id]
    assert service.list_for_contact(bob.id) == []
    assert service.cancel(bob.id, booking.id) is False
    assert service.cancel(alice.id, booking.id) is True
    assert service.cancel(alice.id, booking.id) is False
    assert service.available("Consulta", START, START + SLOT) == [START]
    replacement = service.book(bob.id, "Consulta", START)
    assert replacement.id != booking.id
    session.commit()


def test_conflict_offers_alternatives_and_preserves_transaction(session: Session) -> None:
    contact = Contact(wa_id="15550000001")
    session.add(contact)
    session.flush()
    service = AppointmentService(session)
    service.book(contact.id, "Consulta", START)
    with pytest.raises(AppointmentConflict) as error:
        service.book(contact.id, "consulta", START)
    assert error.value.alternatives == (START + SLOT, START + 2 * SLOT, START + 3 * SLOT)
    assert len(service.list_for_contact(contact.id)) == 1
    session.commit()


def test_different_services_can_share_a_slot(session: Session) -> None:
    contact = Contact(wa_id="15550000001")
    session.add(contact)
    session.flush()
    service = AppointmentService(session)
    service.book(contact.id, "Consulta", START)
    service.book(contact.id, "Avaliação", START)
    assert len(service.list_for_contact(contact.id)) == 2


def test_database_rejects_duplicate_active_slot_even_without_service(session: Session) -> None:
    contact = Contact(wa_id="15550000001")
    session.add(contact)
    session.flush()
    session.add(
        Appointment(
            contact_id=contact.id,
            service="consulta",
            starts_at=START,
            ends_at=START + SLOT,
            status="BOOKED",
        )
    )
    session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(
            Appointment(
                contact_id=contact.id,
                service="consulta",
                starts_at=START,
                ends_at=START + SLOT,
                status="BOOKED",
            )
        )
        session.flush()
    assert len(AppointmentService(session).list_for_contact(contact.id)) == 1


def test_existing_long_appointment_blocks_all_overlapping_slots(session: Session) -> None:
    contact = Contact(wa_id="15550000001")
    session.add(contact)
    session.flush()
    session.add(
        Appointment(
            contact_id=contact.id,
            service="consulta",
            starts_at=START,
            ends_at=START + 2 * SLOT,
            status="BOOKED",
        )
    )
    session.flush()
    service = AppointmentService(session)
    assert service.available("Consulta", START, START + 3 * SLOT) == [START + 2 * SLOT]
    with pytest.raises(AppointmentConflict):
        service.book(contact.id, "Consulta", START + SLOT)


def test_booking_rolls_back_with_caller_transaction(session: Session) -> None:
    contact = Contact(wa_id="15550000001")
    session.add(contact)
    session.commit()
    contact_id = contact.id
    AppointmentService(session).book(contact_id, "Consulta", START)
    session.rollback()
    assert AppointmentService(session).list_for_contact(contact_id) == []


@pytest.mark.parametrize(
    ("name", "at"),
    [
        ("", START),
        ("a" * 256, START),
        ("Consulta", START.replace(tzinfo=None)),
        ("Consulta", START + timedelta(minutes=1)),
        ("Consulta", datetime(2000, 1, 1, tzinfo=UTC)),
    ],
)
def test_invalid_booking_is_rejected(session: Session, name: str, at: datetime) -> None:
    contact = Contact(wa_id="15550000001")
    session.add(contact)
    session.flush()
    with pytest.raises(InvalidAppointment):
        AppointmentService(session).book(contact.id, name, at)
    assert session.scalars(select(Appointment)).all() == []


def test_invalid_availability_ranges_are_rejected(session: Session) -> None:
    service = AppointmentService(session)
    with pytest.raises(InvalidAppointment):
        service.available("Consulta", START, START)
    with pytest.raises(InvalidAppointment):
        service.available("Consulta", START, START + timedelta(days=8))
