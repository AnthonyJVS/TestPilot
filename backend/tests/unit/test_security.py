from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.security import (
    JWT_ALGORITHM,
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from tests.conftest import make_settings

SETTINGS = make_settings("sqlite+aiosqlite:///:memory:")


async def test_password_hash_roundtrip() -> None:
    hashed = await hash_password("correct-horse-battery-staple")
    assert hashed.startswith("$argon2id$")
    assert await verify_password(hashed, "correct-horse-battery-staple")
    assert not await verify_password(hashed, "wrong-password")


async def test_verify_without_hash_is_always_false() -> None:
    assert not await verify_password(None, "anything")


async def test_verify_with_corrupt_hash_is_false() -> None:
    assert not await verify_password("not-a-hash", "anything")


def test_access_token_roundtrip() -> None:
    user_id, session_id = uuid.uuid4(), uuid.uuid4()
    token, expires_at = create_access_token(SETTINGS, user_id=user_id, session_id=session_id)
    claims = decode_access_token(SETTINGS, token)
    assert claims.user_id == user_id
    assert claims.session_id == session_id
    assert abs((claims.expires_at - expires_at).total_seconds()) < 1


def test_tampered_or_foreign_tokens_are_rejected() -> None:
    token, _ = create_access_token(SETTINGS, user_id=uuid.uuid4(), session_id=uuid.uuid4())
    with pytest.raises(InvalidTokenError):
        decode_access_token(SETTINGS, token[:-2] + ("A" if token[-1] != "A" else "B") + token[-1])

    other = make_settings("sqlite+aiosqlite:///:memory:", jwt_secret="another-secret-" + "y" * 40)
    with pytest.raises(InvalidTokenError):
        decode_access_token(other, token)


def test_expired_and_wrong_type_tokens_are_rejected() -> None:
    now = datetime.now(UTC)
    base = {
        "sub": str(uuid.uuid4()),
        "sid": str(uuid.uuid4()),
        "iss": SETTINGS.jwt_issuer,
        "aud": SETTINGS.jwt_audience,
        "iat": int((now - timedelta(hours=2)).timestamp()),
    }
    expired = jwt.encode(
        {**base, "type": "access", "exp": int((now - timedelta(hours=1)).timestamp())},
        SETTINGS.jwt_secret_value,
        algorithm=JWT_ALGORITHM,
    )
    wrong_type = jwt.encode(
        {**base, "type": "refresh", "exp": int((now + timedelta(hours=1)).timestamp())},
        SETTINGS.jwt_secret_value,
        algorithm=JWT_ALGORITHM,
    )
    for token in (expired, wrong_type):
        with pytest.raises(InvalidTokenError):
            decode_access_token(SETTINGS, token)


def test_none_algorithm_is_rejected() -> None:
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "sid": str(uuid.uuid4()), "type": "access"},
        key="",
        algorithm="none",
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(SETTINGS, forged)


def test_refresh_tokens_are_random_and_hashed() -> None:
    a, b = generate_refresh_token(), generate_refresh_token()
    assert a != b and len(a) >= 43
    assert hash_refresh_token(a) == hash_refresh_token(a)
    assert hash_refresh_token(a) != a
