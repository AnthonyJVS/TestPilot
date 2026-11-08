from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Header, Response, status

from app.api.dependencies import AuthServiceDep, Ctx, CurrentUser, SettingsDep
from app.api.errors import error_response
from app.core.config import Settings
from app.domain.exceptions import AppError, AuthenticationError
from app.infrastructure.database.base import utcnow
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.services.auth_service import IssuedTokens

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "tp_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"
CSRF_HEADER_VALUE = "testpilot"


class MissingCsrfHeaderError(AppError):
    code = "auth.csrf_header_missing"
    http_status = 403
    message = "Missing X-Requested-With header."


def _require_csrf_header(value: str | None) -> None:
    # Custom headers cannot be sent cross-site without a CORS preflight we never allow.
    if value != CSRF_HEADER_VALUE:
        raise MissingCsrfHeaderError()


def _set_refresh_cookie(response: Response, settings: Settings, tokens: IssuedTokens) -> None:
    max_age = max(int((tokens.refresh_expires_at - utcnow()).total_seconds()), 0)
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=tokens.refresh_token,
        max_age=max_age,
        path=REFRESH_COOKIE_PATH,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _token_response(settings: Settings, tokens: IssuedTokens) -> TokenResponse:
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=settings.access_token_ttl_seconds,
        expires_at=tokens.access_expires_at,
        user=UserOut.model_validate(tokens.user),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    response: Response,
    auth: AuthServiceDep,
    settings: SettingsDep,
    ctx: Ctx,
) -> TokenResponse:
    tokens = await auth.register(body, ctx)
    _set_refresh_cookie(response, settings, tokens)
    return _token_response(settings, tokens)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    response: Response,
    auth: AuthServiceDep,
    settings: SettingsDep,
    ctx: Ctx,
) -> TokenResponse:
    tokens = await auth.login(body, ctx)
    _set_refresh_cookie(response, settings, tokens)
    return _token_response(settings, tokens)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    auth: AuthServiceDep,
    settings: SettingsDep,
    ctx: Ctx,
    x_requested_with: Annotated[str | None, Header()] = None,
    tp_refresh: Annotated[str | None, Cookie()] = None,
) -> TokenResponse | Response:
    _require_csrf_header(x_requested_with)
    try:
        tokens = await auth.refresh(tp_refresh, ctx)
    except AuthenticationError as exc:
        # A dead refresh token should not linger in the browser.
        failure = error_response(exc.http_status, exc.code, exc.message, exc.details, exc.headers)
        _clear_refresh_cookie(failure, settings)
        return failure
    _set_refresh_cookie(response, settings, tokens)
    return _token_response(settings, tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    auth: AuthServiceDep,
    settings: SettingsDep,
    ctx: Ctx,
    x_requested_with: Annotated[str | None, Header()] = None,
    tp_refresh: Annotated[str | None, Cookie()] = None,
) -> Response:
    _require_csrf_header(x_requested_with)
    await auth.logout(tp_refresh, ctx)
    response.status_code = status.HTTP_204_NO_CONTENT
    _clear_refresh_cookie(response, settings)
    return response


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
