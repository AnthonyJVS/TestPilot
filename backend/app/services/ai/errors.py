"""Normalised provider errors. Adapters translate SDK exceptions into these; nothing else leaks.

``retryable``: worth retrying the same provider after a short wait.
``fallback_eligible``: an explicitly enabled fallback policy may switch providers.
Permanent errors (credentials, permissions, invalid requests) are neither.
"""

from __future__ import annotations


class AIProviderError(Exception):
    code = "ai.provider_error"
    retryable = False
    fallback_eligible = False
    default_message = "The AI provider returned an error."

    def __init__(self, message: str | None = None, *, retry_after: float | None = None) -> None:
        self.message = message or self.default_message
        self.retry_after = retry_after
        super().__init__(self.message)


class AIAuthError(AIProviderError):
    code = "ai.auth_failed"
    default_message = "The provider rejected the API key. Check or rotate the key."


class AIPermissionError(AIProviderError):
    code = "ai.permission_denied"
    default_message = "This API key is not allowed to use the requested model or region."


class AIInvalidRequestError(AIProviderError):
    code = "ai.invalid_request"
    default_message = "The provider rejected the request as invalid."


class AIModelNotFoundError(AIProviderError):
    code = "ai.model_not_found"
    default_message = "The provider does not recognise this model ID."


class AIRateLimitError(AIProviderError):
    code = "ai.rate_limited"
    retryable = True
    fallback_eligible = True
    default_message = "The provider's rate limit was reached."


class AIQuotaExhaustedError(AIProviderError):
    code = "ai.quota_exhausted"
    fallback_eligible = True
    default_message = (
        "The provider quota for this key is exhausted. The task is paused until the quota "
        "resets, or until you choose another model."
    )


class AIUnavailableError(AIProviderError):
    code = "ai.provider_unavailable"
    retryable = True
    fallback_eligible = True
    default_message = "The provider is temporarily unavailable."


class AITimeoutError(AIProviderError):
    code = "ai.timeout"
    retryable = True
    fallback_eligible = True
    default_message = "The provider did not respond in time."


class AIContentFilteredError(AIProviderError):
    code = "ai.content_filtered"
    default_message = "The provider blocked the request or response with a safety filter."


class AIOutputInvalidError(AIProviderError):
    code = "ai.output_invalid"
    default_message = "The model's response did not match the required structure."


class AINotSupportedError(AIProviderError):
    code = "ai.not_supported"
    default_message = "This provider does not support the requested operation."
