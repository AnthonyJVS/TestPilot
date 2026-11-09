"""Google Gemini adapter (Gemini Developer API via the official ``google-genai`` SDK).

Verified against google-genai 3.0.0: ``Client(api_key, http_options)``,
``client.aio.models.generate_content(model, contents, config)``, ``client.aio.models.list()``,
``GenerateContentConfig.response_json_schema`` for native JSON-schema output, ``errors.APIError``
with ``code``/``status``/``details``.
"""

from __future__ import annotations

import re
from typing import Any

import httpx2
from google import genai
from google.genai import errors, types

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
from app.services.ai.providers._common import prompt_with_schema, short
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

_BLOCKED_FINISH = {
    "SAFETY",
    "BLOCKLIST",
    "PROHIBITED_CONTENT",
    "SPII",
    "IMAGE_SAFETY",
    "RECITATION",
}
_DURATION = re.compile(r"^(\d+(?:\.\d+)?)s$")


def _retry_delay(details: Any) -> float | None:
    """Read google.rpc.RetryInfo.retryDelay (e.g. "32s") from an error payload."""
    for item in _error_details(details):
        if str(item.get("@type", "")).endswith("google.rpc.RetryInfo"):
            match = _DURATION.match(str(item.get("retryDelay", "")))
            if match:
                return float(match.group(1))
    return None


def _quota_ids(details: Any) -> list[str]:
    ids: list[str] = []
    for item in _error_details(details):
        if str(item.get("@type", "")).endswith("google.rpc.QuotaFailure"):
            for violation in item.get("violations", []) or []:
                if isinstance(violation, dict) and violation.get("quotaId"):
                    ids.append(str(violation["quotaId"]))
    return ids


def _error_details(details: Any) -> list[dict[str, Any]]:
    if not isinstance(details, dict):
        return []
    error = details.get("error", details)
    items = error.get("details", []) if isinstance(error, dict) else []
    return [item for item in items if isinstance(item, dict)]


# Verified live (2026-11-09, gemini-3.5/3.6-flash): responseJsonSchema with minItems/maxItems
# is rejected with a bare 400 INVALID_ARGUMENT. Array bounds are still enforced by Pydantic after
# the response arrives (with one repair attempt), so they are dropped for Gemini only.
_UNSUPPORTED_SCHEMA_KEYS = frozenset({"minItems", "maxItems"})


def gemini_schema(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            key: gemini_schema(value)
            for key, value in node.items()
            if key not in _UNSUPPORTED_SCHEMA_KEYS
        }
    if isinstance(node, list):
        return [gemini_schema(item) for item in node]
    return node


def map_gemini_error(exc: errors.APIError) -> AIProviderError:
    code = int(exc.code or 0)
    status = str(exc.status or "")
    message = short(exc.message or str(exc))
    reasons = " ".join(str(item.get("reason", "")) for item in _error_details(exc.details))

    if code == 429 or status == "RESOURCE_EXHAUSTED":
        quota_ids = _quota_ids(exc.details)
        if any("PerDay" in quota_id for quota_id in quota_ids):
            return AIQuotaExhaustedError(
                "Gemini daily quota for this key is exhausted "
                f"({', '.join(quota_ids)}). It resets daily; retry later or pick another model."
            )
        return AIRateLimitError(
            f"Gemini rate limit reached: {message}", retry_after=_retry_delay(exc.details)
        )
    if "API_KEY_INVALID" in reasons or code == 401 or status == "UNAUTHENTICATED":
        return AIAuthError("Gemini rejected the API key. Check the key in Google AI Studio.")
    if code == 403 or status == "PERMISSION_DENIED":
        return AIPermissionError(f"Gemini denied access: {message}")
    if code == 404 or status == "NOT_FOUND":
        if "no longer available" in message.lower():
            # Listed by models.list but retired for this account (seen with gemini-2.5-flash).
            return AIModelNotFoundError(
                f"This Gemini model is listed but not available to your key: {message}"
            )
        return AIModelNotFoundError(f"Gemini does not know this model: {message}")
    if status == "FAILED_PRECONDITION":
        return AIPermissionError(f"Gemini is not available for this request: {message}")
    if code in (408, 504) or status == "DEADLINE_EXCEEDED":
        return AITimeoutError("Gemini did not respond in time.")
    if code >= 500 or status in ("UNAVAILABLE", "INTERNAL"):
        return AIUnavailableError(f"Gemini is temporarily unavailable ({code}).")
    return AIInvalidRequestError(f"Gemini rejected the request: {message}")


class GeminiProvider(AIProvider):
    type_id = "gemini"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        http_options = types.HttpOptions(
            timeout=int(self.timeout_seconds * 1000),
            # Retries are owned by the orchestrator so every attempt is recorded.
            retry_options=types.HttpRetryOptions(attempts=1),
            base_url=self.base_url or None,
            httpx_async_client=self.http_client,
        )
        self._client = genai.Client(api_key=self.api_key, http_options=http_options)

    async def list_models(self) -> list[ModelInfo]:
        try:
            pager = await self._client.aio.models.list(config=types.ListModelsConfig(page_size=100))
            models: list[ModelInfo] = []
            async for model in pager:
                actions = model.supported_actions or []
                if "generateContent" not in actions or not model.name:
                    continue
                capabilities = unknown_capabilities()
                capabilities[Capability.TEXT] = CapabilityValue(
                    CapabilityStatus.SUPPORTED, CapabilitySource.PROVIDER_METADATA
                )
                model_id = model.name.removeprefix("models/")
                models.append(
                    ModelInfo(
                        model_id=model_id,
                        display_name=model.display_name or model_id,
                        capabilities=capabilities,
                        input_token_limit=model.input_token_limit,
                        output_token_limit=model.output_token_limit,
                    )
                )
            return models
        except errors.APIError as exc:
            raise map_gemini_error(exc) from exc
        except httpx2.TimeoutException as exc:
            raise AITimeoutError() from exc
        except httpx2.TransportError as exc:
            raise AIUnavailableError(f"Cannot reach Gemini: {type(exc).__name__}") from exc

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        parts: list[Any] = [
            types.Part.from_bytes(data=image.data, mime_type=image.mime_type)
            for image in request.images
        ]
        parts.append(prompt_with_schema(request))
        native = request.json_schema is not None and request.native_structured_output
        config = types.GenerateContentConfig(
            system_instruction=request.system,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
            response_mime_type="application/json" if request.json_schema is not None else None,
            response_json_schema=gemini_schema(request.json_schema) if native else None,
            http_options=types.HttpOptions(timeout=int(request.timeout_seconds * 1000)),
            # TestPilot never passes tools; keep the SDK from looping on function calls.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        try:
            response = await self._client.aio.models.generate_content(
                model=request.model, contents=parts, config=config
            )
        except errors.APIError as exc:
            raise map_gemini_error(exc) from exc
        except httpx2.TimeoutException as exc:
            raise AITimeoutError() from exc
        except httpx2.TransportError as exc:
            raise AIUnavailableError(f"Cannot reach Gemini: {type(exc).__name__}") from exc

        if response.prompt_feedback and response.prompt_feedback.block_reason:
            raise AIContentFilteredError(
                f"Gemini blocked the prompt ({response.prompt_feedback.block_reason})."
            )
        candidate = response.candidates[0] if response.candidates else None
        finish = (
            str(candidate.finish_reason.value) if candidate and candidate.finish_reason else None
        )
        if finish in _BLOCKED_FINISH:
            raise AIContentFilteredError(f"Gemini stopped the response ({finish}).")
        text = response.text or ""
        if not text.strip():
            if finish == "MAX_TOKENS":
                raise AIOutputInvalidError(
                    "Gemini spent the output token budget (often on thinking) before answering."
                )
            raise AIOutputInvalidError("Gemini returned an empty response.")

        usage = response.usage_metadata
        return GenerateResponse(
            text=text,
            actual_model=response.model_version or request.model,
            request_id=response.response_id,
            usage=TokenUsage(
                input_tokens=usage.prompt_token_count if usage else None,
                output_tokens=(
                    (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
                    if usage and (usage.candidates_token_count or usage.thoughts_token_count)
                    else None
                ),
                total_tokens=usage.total_token_count if usage else None,
            ),
            finish_reason=finish,
        )

    async def aclose(self) -> None:
        await self._client.aio.aclose()
