from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    database_url: str = "sqlite:///./atendimento.db"
    redis_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    meta_app_secret: SecretStr | None = None
    meta_verify_token: SecretStr | None = None
    meta_access_token: SecretStr | None = None
    meta_phone_number_id: str | None = None
    meta_graph_api_version: str | None = None
    webhook_max_body_bytes: int = Field(default=1_000_000, gt=0)
    webhook_rate_limit_requests_per_minute: int = Field(default=120, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
