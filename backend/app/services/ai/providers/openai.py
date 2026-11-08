"""OpenAI adapter (official ``openai`` SDK, Chat Completions API).

Verified against openai 3.46.0: ``AsyncOpenAI(api_key, base_url, max_retries, timeout,
http_client)``, ``chat.completions.create(..., response_format={"type": "json_schema", ...},
max_completion_tokens=...)``, ``models.list()``. The model listing API reports no capabilities,
so they stay ``unknown`` until a routing check verifies them.
"""

from __future__ import annotations

import base64
import re
from typing import Any

import openai

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
    GenerateRequest,
    GenerateResponse,
    ModelInfo,
    TokenUsage,
)

# The listing includes embedding, speech, image and moderation models; hide those from the
# picker. Any model ID can still be added manually.
_NON_CHAT = re.compile(
    r"(embedding|tts|whisper|dall-e|davinci|babbage|moderation|transcribe|realtime|"
    r"audio|image|sora|search|computer-use)",
    re.IGNORECASE,
)


def _schema_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", name)[:64]
    return cleaned or "result"


def map_openai_error(exc: Exception) -> AIProviderError:
    if isinstance(exc, openai.AuthenticationError):
        return AIAuthError("OpenAI rejected the API key. Check or rotate it.")
    if isinstance(exc, openai.PermissionDeniedError):
        return AIPermissionError(f"OpenAI denied access: {short(exc.message)}")
    if isinstance(exc, openai.NotFoundError):
        return AIModelNotFoundError(f"OpenAI does not know this model: {short(exc.message)}")
    if isinstance(exc, openai.RateLimitError):
        if getattr(exc, "code", None) == "insufficient_quota":
            return AIQuotaExhaustedError(
                "The OpenAI quota or billing limit for this key is used up."
            )
        retry_after = parse_retry_after(exc.response.headers.get("retry-after"))
        return AIRateLimitError(
            f"OpenAI rate limit reached: {short(exc.message)}", retry_after=retry_after
        )
    if isinstance(exc, openai.BadRequestError | openai.UnprocessableEntityError):
        return AIInvalidRequestError(f"OpenAI rejected the request: {short(exc.message)}")
    if isinstance(exc, openai.APITimeoutError):
        return AITimeoutError("OpenAI did not respond in time.")
    if isinstance(exc, openai.InternalServerError):
        return AIUnavailableError("OpenAI is temporarily unavailable.")
    if isinstance(exc, openai.APIConnectionError):
        return AIUnavailableError("Cannot reach OpenAI.")
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code >= 500:
            return AIUnavailableError(f"OpenAI error {exc.status_code}.")
        return AIInvalidRequestError(f"OpenAI rejected the request: {short(exc.message)}")
    return AIProviderError(f"Unexpected OpenAI error: {type(exc).__name__}")


class OpenAIProvider(AIProvider):
    type_id = "openai"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url or None,
            max_retries=0,  # the orchestrator owns retries
            timeout=self.timeout_seconds,
            http_client=self.http_client,
        )

    async def list_models(self) -> list[ModelInfo]:
        try:
            models = [
                ModelInfo(model_id=model.id, display_name=model.id)
                async for model in self._client.models.list()
                if not _NON_CHAT.search(model.id)
            ]
        except openai.OpenAIError as exc:
            raise map_openai_error(exc) from exc
        return sorted(models, key=lambda m: m.model_id)

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt_with_schema(request)}]
        for image in request.images:
            data = base64.b64encode(image.data).decode("ascii")
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:{image.mime_type};base64,{data}"}}
            )
        messages: list[dict[str, Any]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": content})

        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "max_completion_tokens": request.max_output_tokens,
            "timeout": request.timeout_seconds,
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.json_schema is not None:
            if request.native_structured_output:
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": _schema_name(request.schema_name),
                        "schema": request.json_schema,
                        "strict": False,
                    },
                }
            else:
                kwargs["response_format"] = {"type": "json_object"}
        try:
            completion = await self._client.chat.completions.create(**kwargs)
        except openai.OpenAIError as exc:
            raise map_openai_error(exc) from exc

        choice = completion.choices[0] if completion.choices else None
        if choice is None:
            raise AIOutputInvalidError("OpenAI returned no choices.")
        if getattr(choice.message, "refusal", None):
            raise AIContentFilteredError(f"The model refused: {short(choice.message.refusal)}")
        if choice.finish_reason == "content_filter":
            raise AIContentFilteredError("OpenAI's content filter stopped the response.")
        text = choice.message.content or ""
        if not text.strip():
            if choice.finish_reason == "length":
                raise AIOutputInvalidError(
                    "The model reached the output token limit before answering."
                )
            raise AIOutputInvalidError("OpenAI returned an empty response.")
        usage = completion.usage
        return GenerateResponse(
            text=text,
            actual_model=completion.model,
            request_id=getattr(completion, "_request_id", None) or completion.id,
            usage=TokenUsage(
                input_tokens=usage.prompt_tokens if usage else None,
                output_tokens=usage.completion_tokens if usage else None,
                total_tokens=usage.total_tokens if usage else None,
            ),
            finish_reason=choice.finish_reason,
        )

    async def aclose(self) -> None:
        await self._client.close()
