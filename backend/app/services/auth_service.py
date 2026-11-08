"""Authentication use cases: register, login, refresh (rotation + reuse detection), logout."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_identifier,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    verify_password,
)
from app.domain.exceptions import (
    AuthenticationError,
    ConflictError,
    FeatureDisabledError,
    InvalidCredentialsError,
    RateLimitedError,
)
from app.infrastructure.cache.rate_limiter import RateLimiter
from app.infrastructure.database.base import utcnow
from app.infrastructure.database.models import AuthSession, RefreshToken, User
from app.infrastructure.repositories.identity import AuthSessionRepository, UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services.audit_service import AuditService
from app.services.context import RequestContext

logger = logging.getLogger(__name__)


class RefreshTokenInvalidError(AuthenticationError):
    code = "auth.refresh_invalid"
    message = "Your session has expired. Please sign in again."


class SessionRevokedError(AuthenticationError):
    code = "auth.session_revoked"
    message = "Your session is no longer valid. Please sign in again."


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    user: User
    session_id: uuid.UUID
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings, limiter: RateLimiter) -> None:
        self._db = session
        self._settings = settings
        self._limiter = limiter
        self._users = UserRepository(session)
        self._sessions = AuthSessionRepository(session)
        self._audit = AuditService(session)

    # ------------------------------------------------------------------ register
    async def register(self, data: RegisterRequest, ctx: RequestContext) -> IssuedTokens:
        if not self._settings.allow_registration:
            raise FeatureDisabledError("Registration is disabled on this server.")

        count, ttl = await self._limiter.hit(
            f"register:ip:{ctx.ip_address or 'unknown'}", self._settings.register_window_seconds
        )
        if count > self._settings.register_max_per_ip:
            raise RateLimitedError(ttl)

        if await self._users.get_by_email(data.email) is not None:
            raise ConflictError(
                "An account with this email already exists.", code="auth.email_taken"
            )

        user = User(
            id=uuid.uuid4(),
            email=data.email,
            display_name=data.display_name,
            password_hash=await hash_password(data.password),
            last_login_at=utcnow(),
        )
        self._users.add(user)
        try:
            await self._db.flush()
        except IntegrityError as exc:  # concurrent registration with the same email
            await self._db.rollback()
            raise ConflictError(
                "An account with this email already exists.", code="auth.email_taken"
            ) from exc

        tokens = self._start_session(user, ctx)
        self._audit.record("auth.register", "success", ctx=ctx, user_id=user.id)
        await self._db.commit()
        return tokens

    # --------------------------------------------------------------------- login
    async def login(self, data: LoginRequest, ctx: RequestContext) -> IssuedTokens:
        email_key = f"login:email:{hash_identifier(data.email)}"
        ip_key = f"login:ip:{ctx.ip_address or 'unknown'}"
        window = self._settings.login_failure_window_seconds

        for key, limit in (
            (email_key, self._settings.login_max_failures_per_email),
            (ip_key, self._settings.login_max_failures_per_ip),
        ):
            count, ttl = await self._limiter.peek(key)
            if count >= limit:
                self._audit.record(
                    "auth.login", "denied", ctx=ctx, details={"reason": "rate_limited"}
                )
                await self._db.commit()
                raise RateLimitedError(ttl or window)

        user = await self._users.get_by_email(data.email)
        password_ok = await verify_password(user.password_hash if user else None, data.password)

        if user is None or not password_ok or not user.is_active:
            await self._limiter.hit(email_key, window)
            await self._limiter.hit(ip_key, window)
            reason = (
                "unknown_email" if user is None else ("inactive" if password_ok else "bad_password")
            )
            self._audit.record(
                "auth.login",
                "failure",
                ctx=ctx,
                user_id=user.id if user else None,
                details={"reason": reason},
            )
            await self._db.commit()
            raise InvalidCredentialsError()

        await self._limiter.reset(email_key)
        if password_needs_rehash(user.password_hash):
            user.password_hash = await hash_password(data.password)
        user.last_login_at = utcnow()
        tokens = self._start_session(user, ctx)
        self._audit.record("auth.login", "success", ctx=ctx, user_id=user.id)
        await self._db.commit()
        return tokens

    # ------------------------------------------------------------------- refresh
    async def refresh(self, raw_token: str | None, ctx: RequestContext) -> IssuedTokens:
        if not raw_token:
            raise RefreshTokenInvalidError()
        token = await self._sessions.get_refresh_token(hash_refresh_token(raw_token))
        if token is None:
            raise RefreshTokenInvalidError()

        now = utcnow()
        auth_session = token.session
        user = auth_session.user

        if auth_session.revoked_at is not None or auth_session.expires_at <= now:
            raise SessionRevokedError()
        if not user.is_active:
            await self._sessions.revoke(auth_session.id, reason="user_inactive", at=now)
            await self._db.commit()
            raise SessionRevokedError()
        if token.expires_at <= now:
            raise RefreshTokenInvalidError()

        if token.rotated_at is not None:
            grace = timedelta(seconds=self._settings.refresh_reuse_grace_seconds)
            if now - token.rotated_at > grace:
                # A rotated token was replayed: assume theft and kill the whole family.
                await self._sessions.revoke(auth_session.id, reason="refresh_token_reuse", at=now)
                self._audit.record(
                    "auth.refresh",
                    "denied",
                    ctx=ctx,
                    user_id=user.id,
                    target_type="auth_session",
                    target_id=str(auth_session.id),
                    details={"reason": "refresh_token_reuse"},
                )
                await self._db.commit()
                logger.warning(
                    "Refresh token reuse detected; session revoked",
                    extra={"user_id": str(user.id), "auth_session_id": str(auth_session.id)},
                )
                raise SessionRevokedError()
        else:
            token.rotated_at = now

        auth_session.last_used_at = now
        tokens = self._issue_tokens(user, auth_session)
        await self._db.commit()
        return tokens

    # -------------------------------------------------------------------- logout
    async def logout(self, raw_token: str | None, ctx: RequestContext) -> None:
        if not raw_token:
            return
        token = await self._sessions.get_refresh_token(hash_refresh_token(raw_token))
        if token is None:
            return
        await self._sessions.revoke(token.session_id, reason="logout", at=utcnow())
        self._audit.record(
            "auth.logout",
            "success",
            ctx=ctx,
            user_id=token.session.user_id,
            target_type="auth_session",
            target_id=str(token.session_id),
        )
        await self._db.commit()

    # ------------------------------------------------------------- authenticate
    async def authenticate(self, access_token: str) -> tuple[User, AuthSession]:
        try:
            claims = decode_access_token(self._settings, access_token)
        except InvalidTokenError as exc:
            raise AuthenticationError(
                "Invalid or expired access token.", code="auth.token_invalid"
            ) from exc

        auth_session = await self._sessions.get_with_user(claims.session_id)
        now = utcnow()
        if (
            auth_session is None
            or auth_session.user_id != claims.user_id
            or auth_session.revoked_at is not None
            or auth_session.expires_at <= now
            or not auth_session.user.is_active
        ):
            raise SessionRevokedError()
        return auth_session.user, auth_session

    # ------------------------------------------------------------------ helpers
    def _start_session(self, user: User, ctx: RequestContext) -> IssuedTokens:
        now = utcnow()
        auth_session = AuthSession(
            id=uuid.uuid4(),  # assigned up front so it can be embedded in the access token
            user=user,
            created_at=now,
            last_used_at=now,
            expires_at=now + timedelta(seconds=self._settings.refresh_token_ttl_seconds),
            ip_address=ctx.ip_address,
            user_agent=(ctx.user_agent or "")[:512] or None,
        )
        self._sessions.add(auth_session)
        return self._issue_tokens(user, auth_session)

    def _issue_tokens(self, user: User, auth_session: AuthSession) -> IssuedTokens:
        now = utcnow()
        raw_refresh = generate_refresh_token()
        # A refresh token never outlives its session.
        refresh_expires = min(
            now + timedelta(seconds=self._settings.refresh_token_ttl_seconds),
            auth_session.expires_at,
        )
        self._sessions.add_refresh_token(
            RefreshToken(
                session=auth_session,
                token_hash=hash_refresh_token(raw_refresh),
                created_at=now,
                expires_at=refresh_expires,
            )
        )
        access, access_expires = create_access_token(
            self._settings, user_id=user.id, session_id=auth_session.id
        )
        return IssuedTokens(
            user=user,
            session_id=auth_session.id,
            access_token=access,
            access_expires_at=access_expires,
            refresh_token=raw_refresh,
            refresh_expires_at=refresh_expires,
        )
