from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AnyUrl, BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SmtpSettings(BaseModel):
    host: str | None = None
    port: int = 587
    username: str | None = None
    password: str | None = None
    from_addr: str = "noreply@example.local"
    use_tls: bool = True


class LlmSettings(BaseModel):
    base_url: AnyUrl = Field(default="http://localhost:9000")
    timeout_seconds: int = 30
    model_name: str = "internal-llm"


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["local", "dev", "test", "prod"] = "local"
    app_name: str = "loadguard"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://anomaly:anomaly@localhost:5432/anomaly"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    run_am_time: str = "09:00"
    run_pm_time: str = "14:00"
    scheduler_timezone: str = "Europe/Istanbul"

    internal_api_key: str = "change-me"

    llm_base_url: AnyUrl = Field(default="http://localhost:9000")
    llm_timeout_seconds: int = 30
    llm_model_name: str = "internal-llm"

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "noreply@example.local"
    smtp_use_tls: bool = True

    # Notification recipients (comma-separated)
    critical_alert_recipients: str = ""
    warning_digest_recipients: str = ""
    warning_digest_time: str = "16:00"

    # CORS (comma-separated origins). Example: "http://localhost:5173,https://ops.example.local"
    cors_allow_origins: str = "http://localhost:5173"

    def cors_origins(self) -> list[str]:
        origins: list[str] = []
        for part in (self.cors_allow_origins or "").split(","):
            p = part.strip()
            if p:
                origins.append(p)
        return origins

    def smtp(self) -> SmtpSettings:
        return SmtpSettings(
            host=self.smtp_host,
            port=self.smtp_port,
            username=self.smtp_username,
            password=self.smtp_password,
            from_addr=self.smtp_from,
            use_tls=self.smtp_use_tls,
        )

    def llm(self) -> LlmSettings:
        return LlmSettings(
            base_url=self.llm_base_url,
            timeout_seconds=self.llm_timeout_seconds,
            model_name=self.llm_model_name,
        )


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings()


