from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.logging import RedactingFilter
from app.core.redaction import REDACTED, redact, redact_text
from app.infrastructure.cache.rate_limiter import InMemoryRateLimiter


def test_redacts_sensitive_keys_recursively() -> None:
    data = {
        "email": "ada@example.com",
        "password": "hunter2hunter2",
        "nested": {"api_key": "abc", "Authorization": "Bearer xyz", "safe": [1, {"token": "t"}]},
        "empty_secret": "",
    }
    result = redact(data)
    assert result["email"] == "ada@example.com"
    assert result["password"] == REDACTED
    assert result["nested"]["api_key"] == REDACTED
    assert result["nested"]["Authorization"] == REDACTED
    assert result["nested"]["safe"][1]["token"] == REDACTED
    assert result["empty_secret"] == ""
    assert data["password"] == "hunter2hunter2"  # input not mutated


@pytest.mark.parametrize(
    "secret",
    [
        "Bearer abcdefghijklmnop123",
        "sk-ant-api03-abcdefghijklmnopqrstuvwxyz",
        "sk-proj-abcdefghijklmnopqrstuvwxyz",
        "AIzaSyA1234567890abcdefghijklmnopqrstu",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        "AKIAABCDEFGHIJKLMNOP",
    ],
)
def test_redacts_known_secret_formats_in_text(secret: str) -> None:
    assert secret not in redact_text(f"request failed with credential {secret} attached")


def test_logging_filter_masks_messages_and_extras() -> None:
    record = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "key=%s", ("sk-proj-abcdefghijklmnopqrstuvwxyz",), None
    )
    record.password = "hunter2hunter2"
    RedactingFilter().filter(record)
    assert "sk-proj" not in record.getMessage()
    assert record.password == REDACTED


def test_production_requires_strong_secret_redis_and_postgres() -> None:
    base = {"app_env": "production", "redis_url": "redis://r:6379/0"}
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(_env_file=None, database_url="postgresql+asyncpg://u:p@h/db", **base)  # type: ignore[call-arg]
    with pytest.raises(ValidationError, match="SQLite"):
        Settings(_env_file=None, jwt_secret="z" * 40, **base)  # type: ignore[call-arg]
    with pytest.raises(ValidationError, match="REDIS_URL"):
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            app_env="production",
            jwt_secret="z" * 40,
            database_url="postgresql+asyncpg://u:p@h/db",
        )


def test_development_generates_ephemeral_secret() -> None:
    settings = Settings(_env_file=None, app_env="development")  # type: ignore[call-arg]
    assert len(settings.jwt_secret_value) >= 32


def test_cors_origins_accepts_comma_separated_env() -> None:
    settings = Settings(_env_file=None, cors_origins="http://a.test, http://b.test")  # type: ignore[call-arg]
    assert settings.cors_origins == ["http://a.test", "http://b.test"]


async def test_in_memory_rate_limiter() -> None:
    limiter = InMemoryRateLimiter()
    assert await limiter.peek("k") == (0, 0)
    assert (await limiter.hit("k", 60))[0] == 1
    count, ttl = await limiter.hit("k", 60)
    assert count == 2 and 0 < ttl <= 60
    await limiter.reset("k")
    assert (await limiter.peek("k"))[0] == 0
