from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from src.api.rate_limit import (
    RateLimitUnavailableError,
    WebhookRateLimiter,
    get_rate_limiter,
)
from src.channel.simulator import SimulatorAdapter
from src.config import Settings, get_settings
from src.db.models import WebhookEvent
from src.db.session import get_db
from src.tasks import QueueUnavailableError, enqueue_webhook_event

router = APIRouter(tags=["webhook"])


@router.get("/webhook")
def verify_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    settings: Settings = Depends(get_settings),
) -> Response:
    expected_token = settings.meta_verify_token
    if expected_token is None:
        raise HTTPException(status_code=503, detail="Webhook verification is not configured")
    if (
        hub_mode != "subscribe"
        or hub_verify_token is None
        or not hmac.compare_digest(hub_verify_token, expected_token.get_secret_value())
        or hub_challenge is None
    ):
        raise HTTPException(status_code=403, detail="Webhook verification failed")
    return Response(content=hub_challenge, media_type="text/plain")


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    rate_limiter: WebhookRateLimiter = Depends(get_rate_limiter),
) -> dict[str, str]:
    client_identifier = request.client.host if request.client is not None else "unknown"
    try:
        allowed = await run_in_threadpool(
            rate_limiter.allow,
            client_identifier,
            settings.webhook_rate_limit_requests_per_minute,
        )
    except RateLimitUnavailableError as error:
        raise HTTPException(
            status_code=503,
            detail="Webhook rate-limit service is unavailable",
        ) from error
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Webhook rate limit exceeded",
            headers={"Retry-After": "60"},
        )

    secret = settings.meta_app_secret
    if secret is None:
        raise HTTPException(
            status_code=503,
            detail="Webhook signature validation is not configured",
        )

    body = await _read_limited_body(request, settings.webhook_max_body_bytes)
    if not _is_valid_signature(body, x_hub_signature_256, secret.get_secret_value()):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload_value = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise HTTPException(status_code=400, detail="Webhook body must be valid JSON") from error
    if not isinstance(payload_value, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be a JSON object")

    try:
        event_keys = _extract_event_keys(payload_value)
        SimulatorAdapter().parse_inbound(payload_value)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not event_keys:
        event_keys.append((None, None))

    try:
        await run_in_threadpool(_persist_events, session, payload_value, event_keys)
    except QueueUnavailableError as error:
        raise HTTPException(status_code=503, detail="Webhook event queue is unavailable") from error
    return {"status": "accepted"}


async def _read_limited_body(request: Request, maximum_bytes: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header") from error
        if declared_length < 0:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header")
        if declared_length > maximum_bytes:
            raise HTTPException(status_code=413, detail="Webhook body is too large")

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > maximum_bytes:
            raise HTTPException(status_code=413, detail="Webhook body is too large")
        body.extend(chunk)
    return bytes(body)


def _is_valid_signature(body: bytes, signature: str | None, secret: str) -> bool:
    if signature is None or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def _extract_event_keys(payload: Mapping[str, Any]) -> list[tuple[str | None, str | None]]:
    entries = payload.get("entry", [])
    if not isinstance(entries, list):
        raise ValueError("Webhook entry must be an array")

    event_keys: list[tuple[str | None, str | None]] = []
    seen: set[str] = set()
    for entry_index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ValueError(f"Webhook entry[{entry_index}] must be an object")
        changes = entry.get("changes", [])
        if not isinstance(changes, list):
            raise ValueError(f"Webhook entry[{entry_index}].changes must be an array")
        for change_index, change in enumerate(changes):
            if not isinstance(change, Mapping):
                raise ValueError(f"Webhook changes[{change_index}] must be an object")
            value = change.get("value", {})
            if not isinstance(value, Mapping):
                raise ValueError("Webhook change.value must be an object")
            for collection_name in ("messages", "statuses"):
                items = value.get(collection_name, [])
                if not isinstance(items, list):
                    raise ValueError(f"Webhook {collection_name} must be an array")
                for item_index, item in enumerate(items):
                    if not isinstance(item, Mapping):
                        raise ValueError(
                            f"Webhook {collection_name}[{item_index}] must be an object"
                        )
                    wamid = item.get("id")
                    if not isinstance(wamid, str) or not wamid:
                        raise ValueError(f"Webhook {collection_name}[{item_index}].id is required")
                    if collection_name == "messages":
                        dedupe_key = f"message:{wamid}"
                    else:
                        status = item.get("status")
                        timestamp = item.get("timestamp")
                        if not isinstance(status, str) or not status:
                            raise ValueError(
                                f"Webhook statuses[{item_index}].status is required"
                            )
                        if not isinstance(timestamp, str) or not timestamp:
                            raise ValueError(
                                f"Webhook statuses[{item_index}].timestamp is required"
                            )
                        dedupe_key = f"status:{wamid}:{status}:{timestamp}"
                    if dedupe_key not in seen:
                        event_keys.append((wamid, dedupe_key))
                        seen.add(dedupe_key)
    return event_keys


def _persist_events(
    session: Session,
    payload: dict[str, Any],
    event_keys: list[tuple[str | None, str | None]],
) -> list[str]:
    dialect = session.get_bind().dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        raise RuntimeError(f"Unsupported database dialect for webhook deduplication: {dialect}")

    queued_ids: list[str] = []
    for wamid, dedupe_key in event_keys:
        candidate_id = uuid4()
        values = {
            "id": candidate_id,
            "raw_payload": payload,
            "wamid": wamid,
            "dedupe_key": dedupe_key,
            "processing_status": "PENDING",
            "attempts": 0,
        }
        statement: Any
        if dialect == "postgresql":
            statement = postgresql_insert(WebhookEvent).values(**values).on_conflict_do_nothing(
                index_elements=[WebhookEvent.dedupe_key]
            )
        else:
            statement = sqlite_insert(WebhookEvent).values(**values).on_conflict_do_nothing(
                index_elements=[WebhookEvent.dedupe_key]
            )
        result = session.execute(statement.returning(WebhookEvent.id))
        inserted_id = result.scalar_one_or_none()
        if inserted_id is not None:
            queued_ids.append(str(inserted_id))
        elif dedupe_key is not None:
            existing = session.scalar(
                select(WebhookEvent).where(WebhookEvent.dedupe_key == dedupe_key)
            )
            if existing is not None and existing.processing_status != "PROCESSED":
                queued_ids.append(str(existing.id))

    session.commit()
    for queued_event_id in queued_ids:
        enqueue_webhook_event(queued_event_id)
    return queued_ids
