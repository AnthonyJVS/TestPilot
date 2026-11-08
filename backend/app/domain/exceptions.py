"""Domain-level errors. Each carries a stable machine-readable code.

``http_status`` is a hint used by the API layer's central error handler; services
raise these without knowing about HTTP.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    code: str = "app.error"
    http_status: int = 400
    message: str = "The request could not be processed."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details
        self.headers = headers or {}
        super().__init__(self.message)


class AuthenticationError(AppError):
    code = "auth.unauthenticated"
    http_status = 401
    message = "Authentication is required."


class InvalidCredentialsError(AuthenticationError):
    code = "auth.invalid_credentials"
    message = "Invalid email or password."


class PermissionDeniedError(AppError):
    code = "auth.forbidden"
    http_status = 403
    message = "You do not have permission to perform this action."


class NotFoundError(AppError):
    code = "resource.not_found"
    http_status = 404
    message = "The requested resource was not found."


class ConflictError(AppError):
    code = "resource.conflict"
    http_status = 409
    message = "The resource already exists."


class RateLimitedError(AppError):
    code = "rate_limited"
    http_status = 429
    message = "Too many attempts. Please try again later."

    def __init__(self, retry_after_seconds: int, message: str | None = None) -> None:
        super().__init__(
            message,
            details={"retry_after_seconds": retry_after_seconds},
            headers={"Retry-After": str(max(1, retry_after_seconds))},
        )


class FeatureDisabledError(AppError):
    code = "feature.disabled"
    http_status = 403
    message = "This feature is disabled on this server."
