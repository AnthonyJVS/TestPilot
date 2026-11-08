"""Password hashing (Argon2id), access tokens (JWT) and refresh-token primitives."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"  # noqa: S105 (claim value, not a secret)

# RFC 9106 "second recommended" profile (Argon2id, 64 MiB, t=3, p=4) — argon2-cffi defaults.
_hasher = PasswordHasher()

# Used to equalise timing when an account does not exist.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


async def hash_password(password: str) -> str:
    return await run_in_threadpool(_hasher.hash, password)


async def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-work verification; always runs Argon2 even for unknown users."""

    def _verify() -> bool:
        try:
            return _hasher.verify(password_hash or _DUMMY_HASH, password) and bool(password_hash)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    return await run_in_threadpool(_verify)


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    expires_at: datetime


class InvalidTokenError(Exception):
    """Raised for any access token that is malformed, expired or has bad claims."""


def create_access_token(
    settings: Settings, *, user_id: uuid.UUID, session_id: uuid.UUID
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=settings.access_token_ttl_seconds)
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "type": ACCESS_TOKEN_TYPE,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": secrets.token_hex(8),
    }
    token = jwt.encode(payload, settings.jwt_secret_value, algorithm=JWT_ALGORITHM)
    return token, expires_at


def decode_access_token(settings: Settings, token: str) -> AccessTokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_value,
            algorithms=[JWT_ALGORITHM],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "sid", "exp", "iat", "type"]},
        )
        if payload.get("type") != ACCESS_TOKEN_TYPE:
            raise InvalidTokenError("wrong token type")
        return AccessTokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            session_id=uuid.UUID(payload["sid"]),
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise InvalidTokenError(str(exc)) from exc


def generate_refresh_token() -> str:
    """256 bits of randomness, URL-safe."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """Refresh tokens are high-entropy, so a fast hash is appropriate (no need for Argon2)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_identifier(value: str) -> str:
    """Stable, non-reversible key for rate-limit buckets (avoids storing emails in Redis)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
