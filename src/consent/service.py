from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.db.models import ConsentEvent, Contact


class StaleOptInError(ValueError):
    """The confirmation predates a previous consent decision."""


def _validate(at: datetime, source: str) -> str:
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("consent time must include a timezone")
    source = source.strip()
    if not source or len(source) > 255:
        raise ValueError("consent source must contain 1 to 255 characters")
    return source


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def record_marketing_opt_in(
    session: Session, contact: Contact, *, at: datetime, source: str
) -> None:
    source = _validate(at, source)
    if contact.opt_out_at is not None and _utc(contact.opt_out_at) >= _utc(at):
        raise StaleOptInError("opt-in must follow the most recent opt-out")
    if contact.consented_at is not None and _utc(contact.consented_at) > _utc(at):
        raise StaleOptInError("opt-in must not precede the previous opt-in")
    contact.marketing_consent = True
    contact.consented_at = at
    session.add(
        ConsentEvent(contact_id=contact.id, action="OPT_IN", source=source, occurred_at=at)
    )


def record_opt_out(session: Session, contact: Contact, *, at: datetime, source: str) -> None:
    source = _validate(at, source)
    contact.marketing_consent = False
    if contact.opt_out_at is None or _utc(at) > _utc(contact.opt_out_at):
        contact.opt_out_at = at
    session.add(
        ConsentEvent(contact_id=contact.id, action="OPT_OUT", source=source, occurred_at=at)
    )
