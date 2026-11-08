"""Anthropic Claude adapter (official ``anthropic`` SDK).

Verified against anthropic 2.6.0: ``AsyncAnthropic(api_key, base_url, max_retries, timeout,
http_client)``, ``messages.create(..., output_config={"format": {"type": "json_schema", ...}})``
for native structured output, ``models.list()`` whose ``ModelInfo.capabilities`` reports
``image_input`` and ``structured_outputs`` support.
"""

from __future__ import annotations

import base64
from typing import Any

import anthropic

from app.services.ai.base import AIProvider
from app.services.ai.errors import (
    AIAuthError,
    AIContentFilteredError,
    AIInvalidRequestError,
    AIModelNotFoundError,
    AIOutputInvalidError,
    AIPermissionError,
    AIProviderError,
    AIQuotaExhaustedError,
    AIRateLimitError,
    AITimeoutError,
    AIUnavailableError,
)
from app.services.ai.providers._common import parse_retry_after, prompt_with_schema, short
from app.services.ai.types import (
    Capability,
    CapabilitySource,
    CapabilityStatus,
    CapabilityValue,
    GenerateRequest,
    GenerateResponse,
    ModelInfo,
    TokenUsage,
    unknown_capabilities,
)


def _api_message(exc: anthropic.APIStatusError) -> str:
    return short(getattr(exc, "api_message", None) or str(exc))


def map_anthropic_error(exc: Exception) -> AIProviderError:
    if isinstance(exc, anthropic.EnforcedSpendLimitReachedError):
        return AIQuotaExhaustedError("The Anthropic spend limit for this key has been reached.")
    if isinstance(exc, anthropic.AuthenticationError):
        return AIAuthError("Anthropic rejected the API key. Check or rotate it in the console.")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return AIPermissionError(f"Anthropic denied access: {_api_message(exc)}")
    if isinstance(exc, anthropic.NotFoundError):
        return AIModelNotFoundError(f"Anthropic does not know this model: {_api_message(exc)}")
    if isinstance(exc, anthropic.RateLimitError):
        retry_after = parse_retry_after(exc.response.headers.get("retry-after"))
        return AIRateLimitError(
            f"Anthropic rate limit reached: {_api_message(exc)}", retry_after=retry_after
        )
    if isinstance(exc, anthropic.BadRequestError):
        message = _api_message(exc)
        if "credit balance" in message.lower():
            return AIQuotaExhaustedError(f"Anthropic billing limit: {message}")
        return AIInvalidRequestError(f"Anthropic rejected the request: {message}")
    if isinstance(exc, anthropic.APITimeoutError | anthropic.RequestTimeoutError):
        return AITimeoutError("Anthropic did not respond in time.")
    if isinstance(exc, anthropic.InternalServerError):  # 500, 503, 504, 529 overloaded
        return AIUnavailableError(f"Anthropic is temporarily unavailable: {_api_message(exc)}")
    if isinstance(exc, anthropic.APIConnectionError):
        return AIUnavailableError("Cannot reach Anthropic.")
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code >= 500:
            return AIUnavailableError(f"Anthropic error {exc.status_code}.")
        return AIInvalidRequestError(f"Anthropic rejected the request: {_api_message(exc)}")
    return AIProviderError(f"Unexpected Anthropic error: {type(exc).__name__}")


def _support(flag: Any) -> CapabilityValue:
    supported = getattr(flag, "supported", None)
    if supported is None:
        return CapabilityValue(CapabilityStatus.UNKNOWN)
    return CapabilityValue(
        CapabilityStatus.SUPPORTED if supported else CapabilityStatus.UNSUPPORTED,
        CapabilitySource.PROVIDER_METADATA,
    )


class AnthropicProvider(AIProvider):
    type_id = "anthropic"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._client = anthropic.AsyncAnthropic(
            api_key=self.api_key,
            base_url=self.base_url or None,
            max_retries=0,  # the orchestrator owns retries
            timeout=self.timeout_seconds,
            http_client=self.http_client,
        )

    async def list_models(self) -> list[ModelInfo]:
        try:
            models: list[ModelInfo] = []
            async for model in self._client.models.list(limit=100):
                capabilities = unknown_capabilities()
                capabilities[Capability.TEXT] = CapabilityValue(
                    CapabilityStatus.SUPPORTED, CapabilitySource.PROVIDER_METADATA
                )
                if model.capabilities is not None:
                    capabilities[Capability.VISION] = _support(model.capabilities.image_input)
                    capabilities[Capability.STRUCTURED_OUTPUT] = _support(
                        model.capabilities.structured_outputs
                    )
                models.append(
                    ModelInfo(
                        model_id=model.id,
                        display_name=model.display_name or model.id,
                        capabilities=capabilities,
                        input_token_limit=getattr(model, "max_input_tokens", None),
                        output_token_limit=getattr(model, "max_tokens", None),
                    )
                )
            return models
        except anthropic.AnthropicError as exc:
            raise map_anthropic_error(exc) from exc

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image.mime_type,
                    "data": base64.b64encode(image.data).decode("ascii"),
                },
            }
            for image in request.images
        ]
        content.append({"type": "text", "text": prompt_with_schema(request)})
        kwargs: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_output_tokens,
            "messages": [{"role": "user", "content": content}],
            "timeout": request.timeout_seconds,
        }
        if request.system:
            kwargs["system"] = request.system
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.json_schema is not None and request.native_structured_output:
            kwargs["output_config"] = {
                "format": {"type": "json_schema", "schema": request.json_schema}
            }
        try:
            message = await self._client.messages.create(**kwargs)
        except anthropic.AnthropicError as exc:
            raise map_anthropic_error(exc) from exc

        if message.stop_reason == "refusal":
            raise AIContentFilteredError("Claude declined to answer this request.")
        text = "".join(
            getattr(block, "text", "") for block in message.content if block.type == "text"
        )
        if not text.strip():
            if message.stop_reason == "max_tokens":
                raise AIOutputInvalidError(
                    "Claude reached the output token limit before answering."
                )
            raise AIOutputInvalidError("Claude returned an empty response.")
        usage = message.usage
        input_tokens = usage.input_tokens if usage else None
        output_tokens = usage.output_tokens if usage else None
        return GenerateResponse(
            text=text,
            actual_model=message.model,
            request_id=getattr(message, "_request_id", None) or message.id,
            usage=TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=(input_tokens or 0) + (output_tokens or 0) if usage else None,
            ),
            finish_reason=message.stop_reason,
        )

    async def aclose(self) -> None:
        await self._client.close()
