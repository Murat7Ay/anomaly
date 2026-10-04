from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables prefixed with LG_ (12-factor)."""

    model_config = SettingsConfigDict(
        env_prefix="LG_", env_file=".env", extra="ignore", env_ignore_empty=True
    )

    env: Literal["local", "test", "staging", "prod"] = "local"
    log_level: str = "INFO"
    log_json: bool = False

    database_url: str = "postgresql+psycopg://loadguard:loadguard@127.0.0.1:55432/loadguard"

    # Auth. "dev" issues tokens for seeded users without a password (local/demo only).
    # "oidc" is the production path (corporate IdP: AD FS / Keycloak / Entra ID).
    auth_mode: Literal["dev", "oidc"] = "dev"
    jwt_secret: SecretStr = SecretStr("dev-only-change-me-dev-only-change-me")
    jwt_ttl_minutes: int = 12 * 60
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None

    # Machine-to-machine ingestion (SFTP watcher / API gateway).
    ingest_api_key: SecretStr = SecretStr("dev-ingest-key")

    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    # Advisory AI. "none" => deterministic templates only.
    ai_provider: Literal["none", "openai_compatible", "anthropic"] = "none"
    ai_base_url: str | None = None
    ai_model: str | None = None
    ai_api_key: SecretStr | None = None
    ai_timeout_seconds: float = 60.0
    # None = provider default. Some (reasoning) models reject anything else; on-prem models can use 0.
    ai_temperature: float | None = None

    # Where the operations team lives: "today", dashboards and contract lookups use this zone.
    # Each contract still carries its own timezone/calendar for the institution's schedule.
    operating_timezone: str = "Europe/Istanbul"
    default_calendar: str = "TR"

    # Challenger models evaluated in shadow mode (comma-separated names from domain.challengers).
    shadow_challengers: str = "mix-shift-v2"
    worker_stale_after_seconds: int = 120

    notify_webhook_url: str | None = None
    public_base_url: str = "http://localhost:8080"

    worker_poll_seconds: float = 2.0
    worker_tick_seconds: float = 30.0
    simulator_live: bool = Field(
        default=False, description="Demo: ingest planned synthetic loads as time passes"
    )

    def shadow_list(self) -> list[str]:
        return [x.strip() for x in self.shadow_challengers.split(",") if x.strip()]

    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
