from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from src.db.models import Appointment

_SLOT = timedelta(minutes=30)
_MAX_RANGE = timedelta(days=7)


class InvalidAppointment(ValueError):
    """The simulated appointment request is invalid."""


class AppointmentConflict(ValueError):
    def __init__(self, alternatives: tuple[datetime, ...]) -> None:
        super().__init__("The appointment slot is already booked")
        self.alternatives = alternatives


class AppointmentService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def available(self, service: str, start: datetime, end: datetime) -> list[datetime]:
        name = _service_name(service)
        start = _slot_time(start)
        end = _slot_time(end)
        if end <= start or end - start > _MAX_RANGE:
            raise InvalidAppointment("availability range must be positive and at most seven days")
        occupied = self._session.execute(
            select(Appointment.starts_at, Appointment.ends_at).where(
                Appointment.service == name,
                Appointment.status == "BOOKED",
                Appointment.starts_at < end,
                Appointment.ends_at > start,
            )
        ).all()
        booked = [(_utc(a), _utc(b)) for a, b in occupied]
        return [
            start + index * _SLOT
            for index in range((end - start) // _SLOT)
            if not any(
                start + index * _SLOT < booked_end
                and start + (index + 1) * _SLOT > booked_start
                for booked_start, booked_end in booked
            )
        ]

    def book(self, contact_id: UUID, service: str, start: datetime) -> Appointment:
        name = _service_name(service)
        start = _slot_time(start)
        if start <= datetime.now(UTC):
            raise InvalidAppointment("appointment must be in the future")
        if not self.available(name, start, start + _SLOT):
            raise self._conflict(name, start)
        dialect = self._session.get_bind().dialect.name
        values = {
            "contact_id": contact_id,
            "service": name,
            "starts_at": start,
            "ends_at": start + _SLOT,
            "status": "BOOKED",
        }
        if dialect == "postgresql":
            pg_statement = (
                postgresql_insert(Appointment)
                .values(**values)
                .on_conflict_do_nothing(
                    index_elements=[Appointment.service, Appointment.starts_at],
                    index_where=text("status = 'BOOKED'"),
                )
                .returning(Appointment)
            )
            appointment = self._session.scalar(pg_statement)
        elif dialect == "sqlite":
            sqlite_statement = (
                sqlite_insert(Appointment)
                .values(**values)
                .on_conflict_do_nothing(
                    index_elements=[Appointment.service, Appointment.starts_at],
                    index_where=text("status = 'BOOKED'"),
                )
                .returning(Appointment)
            )
            appointment = self._session.scalar(sqlite_statement)
        else:
            raise RuntimeError(f"Unsupported appointment database dialect: {dialect}")
        if appointment is None:
            raise self._conflict(name, start) from None
        return appointment

    def _conflict(self, name: str, start: datetime) -> AppointmentConflict:
        alternatives = self.available(name, start + _SLOT, start + _MAX_RANGE)[:3]
        return AppointmentConflict(tuple(alternatives))

    def list_for_contact(self, contact_id: UUID) -> list[Appointment]:
        return list(
            self._session.scalars(
                select(Appointment)
                .where(Appointment.contact_id == contact_id)
                .order_by(Appointment.starts_at)
            )
        )

    def cancel(self, contact_id: UUID, appointment_id: UUID) -> bool:
        statement = (
            update(Appointment)
            .where(
                Appointment.id == appointment_id,
                Appointment.contact_id == contact_id,
                Appointment.status == "BOOKED",
            )
            .values(status="CANCELLED")
            .returning(Appointment.id)
        )
        return self._session.scalar(statement) is not None


def _service_name(service: str) -> str:
    name = service.strip().casefold()
    if not name or len(name) > 255:
        raise InvalidAppointment("service must contain 1 to 255 characters")
    return name


def _slot_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidAppointment("appointment time must include a timezone")
    result = value.astimezone(UTC)
    if result.minute not in (0, 30) or result.second or result.microsecond:
        raise InvalidAppointment("appointment time must align to a 30-minute UTC slot")
    return result


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
