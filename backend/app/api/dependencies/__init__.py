"""FastAPI dependencies: settings, DB session, services, current user."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import request_id_var
from app.domain.exceptions import AuthenticationError
from app.infrastructure.cache.rate_limiter import RateLimiter
from app.infrastructure.database.models import AuthSession, User
from app.services.auth_service import AuthService
from app.services.context import RequestContext

_bearer = HTTPBearer(auto_error=False, description="Access token from /auth/login")


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_rate_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


def get_request_context(request: Request) -> RequestContext:
    return RequestContext(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=request_id_var.get(),
    )


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
DbSession = Annotated[AsyncSession, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]


def get_auth_service(
    db: DbSession, settings: SettingsDep, limiter: Annotated[RateLimiter, Depends(get_rate_limiter)]
) -> AuthService:
    return AuthService(db, settings, limiter)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_session(
    auth: AuthServiceDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> tuple[User, AuthSession]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError()
    return await auth.authenticate(credentials.credentials)


async def get_current_user(
    current: Annotated[tuple[User, AuthSession], Depends(get_current_session)],
) -> User:
    return current[0]


CurrentUser = Annotated[User, Depends(get_current_user)]
