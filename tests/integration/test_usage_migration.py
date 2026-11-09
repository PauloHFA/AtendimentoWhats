from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db.models import Contact, Conversation, Message
from src.usage.service import record_sent_message


def test_downgrade_refuses_to_discard_idempotency_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"sqlite:///{tmp_path / 'usage.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = create_engine(url)
    with Session(engine) as session:
        message = Message(
            conversation=Conversation(contact=Contact(wa_id="15550000001")),
            wamid="wamid.example",
            direction="OUTBOUND",
            message_type="template",
            content={},
            delivery_status="SENT",
        )
        session.add(message)
        session.flush()
        record_sent_message(
            session,
            message.id,
            phone_number_id="123",
            category="utility",
            sent_at=datetime.now(UTC),
        )
        session.commit()
    with pytest.raises(RuntimeError, match="Cannot downgrade"):
        command.downgrade(config, "0004_consent_history")
    engine.dispose()
