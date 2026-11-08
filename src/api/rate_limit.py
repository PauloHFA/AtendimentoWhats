from __future__ import annotations

import hashlib
import time
from functools import lru_cache
from typing import Protocol

from redis import Redis
from redis.exceptions import RedisError

from src.config import get_settings

_INCREMENT_WITH_EXPIRY = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


class RateLimitUnavailableError(RuntimeError):
    """Raised when the shared rate-limit store is unavailable."""


class WebhookRateLimiter(Protocol):
    def allow(self, client_identifier: str, requests_per_minute: int) -> bool: ...


class RedisWebhookRateLimiter:
    def __init__(self, redis_url: str) -> None:
        self._redis = Redis.from_url(
            redis_url,
            socket_connect_timeout=1,
            socket_timeout=1,
            health_check_interval=30,
        )

    def allow(self, client_identifier: str, requests_per_minute: int) -> bool:
        window_seconds = 60
        window = int(time.time()) // window_seconds
        client_hash = hashlib.sha256(client_identifier.encode("utf-8")).hexdigest()
        key = f"webhook:rate:{window}:{client_hash}"
        try:
            count = self._redis.eval(_INCREMENT_WITH_EXPIRY, 1, key, window_seconds)
        except RedisError as error:
            raise RateLimitUnavailableError("Webhook rate-limit store is unavailable") from error
        return int(count) <= requests_per_minute


@lru_cache
def get_rate_limiter() -> WebhookRateLimiter:
    return RedisWebhookRateLimiter(get_settings().redis_url)
