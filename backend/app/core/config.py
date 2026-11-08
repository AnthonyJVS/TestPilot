"""Application settings loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

import logging
import secrets
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

logger = logging.getLogger(__name__)

AppEnv = Literal["development", "test", "production"]

MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """All runtime configuration. Never log this object directly."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "TestPilot"
    app_env: AppEnv = "development"
    app_version: str = "0.1.0"

    database_url: str = "sqlite+aiosqlite:///./data/testpilot.db"
    database_echo: bool = False
    redis_url: str | None = None

    jwt_secret: SecretStr | None = None
    jwt_issuer: str = "testpilot"
    jwt_audience: str = "testpilot-api"
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    refresh_token_ttl_seconds: int = Field(default=14 * 24 * 3600, ge=3600, le=90 * 24 * 3600)
    refresh_reuse_grace_seconds: int = Field(default=20, ge=0, le=120)

    cookie_secure: bool = True
    cookie_domain: str | None = None

    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    allow_registration: bool = True
    enable_api_docs: bool = True

    login_max_failures_per_email: int = Field(default=5, ge=1)
    login_max_failures_per_ip: int = Field(default=20, ge=1)
    login_failure_window_seconds: int = Field(default=900, ge=60)
    register_max_per_ip: int = Field(default=10, ge=1)
    register_window_seconds: int = Field(default=3600, ge=60)

    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _validate_security(self) -> Settings:
        secret = self.jwt_secret.get_secret_value() if self.jwt_secret else ""
        if self.app_env == "production":
            if len(secret) < MIN_JWT_SECRET_LENGTH:
                raise ValueError(
                    f"JWT_SECRET must be set to at least {MIN_JWT_SECRET_LENGTH} characters "
                    "in production."
                )
            if not self.redis_url:
                raise ValueError("REDIS_URL is required in production (rate limiting).")
            if self.database_url.startswith("sqlite"):
                raise ValueError("SQLite is not supported in production; use PostgreSQL.")
            if not self.cookie_secure:
                logger.warning(
                    "COOKIE_SECURE is false: refresh cookies will be sent over plain HTTP. "
                    "Only acceptable for a localhost demo; enable it behind HTTPS."
                )
        elif not secret:
            # Development/test convenience: an ephemeral secret. Tokens become invalid on restart.
            self.jwt_secret = SecretStr(secrets.token_urlsafe(48))
            logger.warning("JWT_SECRET is not set; using an ephemeral development secret.")
        elif len(secret) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(f"JWT_SECRET must be at least {MIN_JWT_SECRET_LENGTH} characters.")
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def jwt_secret_value(self) -> str:
        assert self.jwt_secret is not None  # guaranteed by the validator
        return self.jwt_secret.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    return Settings()
