"""Application-level AI errors (mapped to the API error envelope)."""

from __future__ import annotations

from typing import Any

from app.domain.exceptions import AppError
from app.services.ai.errors import AIProviderError, AIQuotaExhaustedError, AIRateLimitError


class ProviderTypeUnavailableError(AppError):
    code = "ai.provider_type_unavailable"
    http_status = 400
    message = "This provider type is not available yet."


class CredentialMissingError(AppError):
    code = "ai.credential_missing"
    http_status = 409
    message = "This provider connection has no API key. Add one first."


class CredentialUnreadableError(AppError):
    code = "ai.credential_unreadable"
    http_status = 409
    message = (
        "The stored API key cannot be decrypted with the configured encryption keys. "
        "Enter the key again."
    )


class RoutingNotConfiguredError(AppError):
    code = "ai.routing_not_configured"
    http_status = 409
    message = "No model is selected for this task. Choose a default model on the AI Providers page."


class CapabilityMissingError(AppError):
    code = "ai.capability_missing"
    http_status = 422
    message = "The selected model does not support what this task needs."


class UsageLimitReachedError(AppError):
    code = "ai.usage_limit_reached"
    http_status = 429
    message = "Your daily AI request limit is reached. AI work is paused until tomorrow (UTC)."


class UnsafeBaseUrlError(AppError):
    code = "ai.base_url_rejected"
    http_status = 422
    message = "The endpoint URL must be a public HTTPS address."


class AITaskFailedError(AppError):
    """A provider call failed after retries (and fallback, when enabled)."""

    http_status = 502

    def __init__(self, error: AIProviderError, *, provider: str, model: str) -> None:
        details: dict[str, Any] = {
            "provider": provider,
            "model": model,
            "retryable": error.retryable,
            "retry_after_seconds": error.retry_after,
        }
        headers: dict[str, str] = {}
        if isinstance(error, AIRateLimitError | AIQuotaExhaustedError):
            self.http_status = 429
            if error.retry_after:
                headers["Retry-After"] = str(int(error.retry_after) + 1)
        super().__init__(error.message, code=error.code, details=details, headers=headers)
        self.provider_error = error
