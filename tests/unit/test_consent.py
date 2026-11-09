from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.consent.service import record_marketing_opt_in, record_opt_out
from src.db.models import Base, ConsentEvent, Contact

NOW = datetime(2030, 1, 1, tzinfo=UTC)


def test_explicit_opt_in_and_opt_out_record_history_in_transaction() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        contact = Contact(wa_id="15550000001")
        session.add(contact)
        session.flush()
        record_marketing_opt_in(session, contact, at=NOW, source="explicit_test")
        assert contact.marketing_consent
        record_opt_out(session, contact, at=NOW + timedelta(seconds=1), source="wamid.1")
        assert not contact.marketing_consent
        session.flush()
        events = session.scalars(select(ConsentEvent).order_by(ConsentEvent.recorded_at)).all()
        assert [event.action for event in events] == ["OPT_IN", "OPT_OUT"]
        session.rollback()
    engine.dispose()


def test_opt_in_requires_evidence_and_cannot_override_newer_opt_out() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        contact = Contact(wa_id="15550000001")
        session.add(contact)
        session.flush()
        record_opt_out(session, contact, at=NOW, source="wamid.1")
        with pytest.raises(ValueError):
            record_marketing_opt_in(session, contact, at=NOW, source=" ")
        with pytest.raises(ValueError):
            record_marketing_opt_in(session, contact, at=NOW, source="older_confirmation")
        assert not contact.marketing_consent
    engine.dispose()
