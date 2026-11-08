"""Central error handling: every failure uses the same JSON envelope."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_var
from app.domain.exceptions import AppError

logger = logging.getLogger(__name__)

_HTTP_CODES = {
    400: "request.bad_request",
    401: "auth.unauthenticated",
    403: "auth.forbidden",
    404: "resource.not_found",
    405: "request.method_not_allowed",
    409: "resource.conflict",
    413: "request.too_large",
    415: "request.unsupported_media_type",
    429: "rate_limited",
}


def error_response(
    status: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id_var.get(),
            "details": details,
        }
    }
    return JSONResponse(status_code=status, content=body, headers=headers)


def _sanitize_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    # Pydantic includes the offending ``input`` (which may be a password); never echo it.
    return [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.http_status, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            422,
            "request.validation_failed",
            "The request is invalid.",
            _sanitize_validation_errors(exc),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "request.error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        headers = dict(exc.headers) if exc.headers else None
        return error_response(exc.status_code, code, message, headers=headers)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=exc)
        return error_response(500, "internal_error", "An unexpected error occurred.")
