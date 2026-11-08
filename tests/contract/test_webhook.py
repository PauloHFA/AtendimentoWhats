import hashlib
import hmac
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from src.api.rate_limit import get_rate_limiter
from src.config import Settings, get_settings
from src.db.models import Base, WebhookEvent
from src.db.session import get_db
from src.main import app
from src.tasks import QueueUnavailableError

APP_SECRET = "test-app-secret"
VERIFY_TOKEN = "test-verify-token"


class AllowAllRateLimiter:
    def allow(self, client_identifier: str, requests_per_minute: int) -> bool:
        return True


@pytest.fixture
def webhook_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, sessionmaker[Session], list[str]]]:
    database_path = tmp_path / "webhook-test.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    test_session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db() -> Iterator[Session]:
        with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url=database_url,
        meta_app_secret=APP_SECRET,
        meta_verify_token=VERIFY_TOKEN,
        webhook_max_body_bytes=1024,
    )
    app.dependency_overrides[get_rate_limiter] = AllowAllRateLimiter
    queued: list[str] = []
    monkeypatch.setattr("src.api.webhook.enqueue_webhook_event", queued.append)

    with TestClient(app) as client:
        yield client, test_session_factory, queued

    app.dependency_overrides.clear()
    engine.dispose()


def _signature(body: bytes, secret: str = APP_SECRET) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _message_payload(*message_ids: str) -> dict[str, object]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "test-account",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messages": [
                                {
                                    "id": message_id,
                                    "from": "15550001111",
                                    "timestamp": "1731000000",
                                    "type": "text",
                                    "text": {"body": "Oi"},
                                }
                                for message_id in message_ids
                            ]
                        },
                    }
                ],
            }
        ],
    }


def _raw(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode()


def test_get_webhook_returns_challenge_for_valid_subscribe(
    webhook_client: tuple[TestClient, sessionmaker[Session], list[str]],
) -> None:
    client, _, _ = webhook_client

    response = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "challenge-value",
        },
    )

    assert response.status_code == 200
    assert response.text == "challenge-value"


def test_get_webhook_rejects_incorrect_token(
    webhook_client: tuple[TestClient, sessionmaker[Session], list[str]],
) -> None:
    client, _, _ = webhook_client

    response = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "challenge-value",
        },
    )

    assert response.status_code == 403


def test_post_webhook_rejects_invalid_signature_without_persisting(
    webhook_client: tuple[TestClient, sessionmaker[Session], list[str]],
) -> None:
    client, session_factory, _ = webhook_client
    body = _raw(_message_payload("wamid.invalid"))

    response = client.post(
        "/webhook", content=body, headers={"X-Hub-Signature-256": "sha256=invalid"}
    )

    assert response.status_code == 401
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(WebhookEvent)) == 0


def test_post_webhook_enforces_rate_limit_before_body_processing(
    webhook_client: tuple[TestClient, sessionmaker[Session], list[str]],
) -> None:
    client, session_factory, _ = webhook_client

    class RejectAllRateLimiter:
        def allow(self, client_identifier: str, requests_per_minute: int) -> bool:
            return False

    app.dependency_overrides[get_rate_limiter] = RejectAllRateLimiter
    response = client.post("/webhook", content=b"not-json")

    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(WebhookEvent)) == 0


def test_post_webhook_persists_and_enqueues_signed_event(
    webhook_client: tuple[TestClient, sessionmaker[Session], list[str]],
) -> None:
    client, session_factory, queued = webhook_client
    body = _raw(_message_payload("wamid.valid"))

    response = client.post(
        "/webhook", content=body, headers={"X-Hub-Signature-256": _signature(body)}
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    with session_factory() as session:
        event = session.scalar(select(WebhookEvent))
        assert event is not None
        assert event.wamid == "wamid.valid"
        assert event.raw_payload == json.loads(body)
        assert event.processing_status == "PENDING"
        assert queued == [str(event.id)]


def test_duplicate_wamid_is_stored_once_and_redelivered_to_worker(
    webhook_client: tuple[TestClient, sessionmaker[Session], list[str]],
) -> None:
    client, session_factory, queued = webhook_client
    body = _raw(_message_payload("wamid.duplicate"))
    headers = {"X-Hub-Signature-256": _signature(body)}

    first = client.post("/webhook", content=body, headers=headers)
    second = client.post("/webhook", content=body, headers=headers)

    assert first.status_code == second.status_code == 200
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(WebhookEvent)) == 1
    assert len(queued) == 2
    assert queued[0] == queued[1]


def test_post_webhook_rejects_oversized_body(
    webhook_client: tuple[TestClient, sessionmaker[Session], list[str]],
) -> None:
    client, session_factory, _ = webhook_client
    body = b" " * 1025

    response = client.post(
        "/webhook", content=body, headers={"X-Hub-Signature-256": _signature(body)}
    )

    assert response.status_code == 413
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(WebhookEvent)) == 0


def test_post_webhook_rejects_invalid_json_after_signature_validation(
    webhook_client: tuple[TestClient, sessionmaker[Session], list[str]],
) -> None:
    client, session_factory, _ = webhook_client
    body = b"{invalid json"

    response = client.post(
        "/webhook", content=body, headers={"X-Hub-Signature-256": _signature(body)}
    )

    assert response.status_code == 400
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(WebhookEvent)) == 0


def test_post_webhook_enqueues_each_message_in_batch(
    webhook_client: tuple[TestClient, sessionmaker[Session], list[str]],
) -> None:
    client, session_factory, queued = webhook_client
    body = _raw(_message_payload("wamid.batch-1", "wamid.batch-2"))

    response = client.post(
        "/webhook", content=body, headers={"X-Hub-Signature-256": _signature(body)}
    )

    assert response.status_code == 200
    with session_factory() as session:
        events = session.scalars(select(WebhookEvent).order_by(WebhookEvent.wamid)).all()
    assert [event.wamid for event in events] == ["wamid.batch-1", "wamid.batch-2"]
    assert len(queued) == 2


def test_distinct_status_updates_for_same_wamid_are_not_deduplicated(
    webhook_client: tuple[TestClient, sessionmaker[Session], list[str]],
) -> None:
    client, session_factory, queued = webhook_client
    statuses = [
        {"id": "wamid.outgoing", "status": state, "timestamp": timestamp}
        for state, timestamp in (("sent", "100"), ("delivered", "101"), ("read", "102"))
    ]
    payload: dict[str, object] = {
        "entry": [
            {
                "changes": [
                    {"field": "messages", "value": {"statuses": statuses}},
                ]
            }
        ]
    }
    body = _raw(payload)

    response = client.post(
        "/webhook", content=body, headers={"X-Hub-Signature-256": _signature(body)}
    )

    assert response.status_code == 200
    with session_factory() as session:
        events = session.scalars(
            select(WebhookEvent).order_by(WebhookEvent.dedupe_key)
        ).all()
    assert len(events) == 3
    assert {event.wamid for event in events} == {"wamid.outgoing"}
    assert len(queued) == 3


def test_post_webhook_can_retry_queue_publish_for_duplicate_event(
    webhook_client: tuple[TestClient, sessionmaker[Session], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory, _ = webhook_client
    body = _raw(_message_payload("wamid.retry"))
    headers = {"X-Hub-Signature-256": _signature(body)}

    def publish_failure(_: str) -> None:
        raise QueueUnavailableError("queue unavailable")

    monkeypatch.setattr("src.api.webhook.enqueue_webhook_event", publish_failure)
    first = client.post("/webhook", content=body, headers=headers)

    queued: list[str] = []
    monkeypatch.setattr("src.api.webhook.enqueue_webhook_event", queued.append)
    retry = client.post("/webhook", content=body, headers=headers)

    assert first.status_code == 503
    assert retry.status_code == 200
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(WebhookEvent)) == 1
    assert len(queued) == 1


def test_settings_used_by_test_fixture_include_expected_values() -> None:
    settings = Settings(meta_app_secret=APP_SECRET, meta_verify_token=VERIFY_TOKEN)

    assert settings.meta_app_secret is not None
    assert settings.meta_app_secret.get_secret_value() == APP_SECRET
    assert settings.meta_verify_token is not None
    assert settings.meta_verify_token.get_secret_value() == VERIFY_TOKEN
