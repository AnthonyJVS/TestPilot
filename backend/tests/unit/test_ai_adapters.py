"""Adapters exercised through the real SDKs against a mock HTTP transport.

These check what goes over the wire (structured-output parameters, images, auth headers) and how
provider error responses are normalised — without network access or real keys.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import httpx2
import pytest

from app.services.ai.errors import (
    AIAuthError,
    AIContentFilteredError,
    AIModelNotFoundError,
    AIQuotaExhaustedError,
    AIRateLimitError,
    AIUnavailableError,
)
from app.services.ai.providers.anthropic import AnthropicProvider
from app.services.ai.providers.gemini import GeminiProvider
from app.services.ai.providers.openai import OpenAIProvider
from app.services.ai.task_checks import solid_png
from app.services.ai.types import Capability, CapabilityStatus, GenerateRequest, ImageInput

SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}

Handler = Callable[[httpx2.Request], httpx2.Response]


class Recorder:
    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.handler(request)

    def body(self, index: int = -1) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(self.requests[index].content)
        return result


def client(recorder: Recorder) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(recorder))


def structured_request(**overrides: Any) -> GenerateRequest:
    values: dict[str, Any] = {
        "model": "test-model",
        "prompt": "Summarise.",
        "system": "Be brief.",
        "json_schema": SCHEMA,
        "schema_name": "Summary",
        "max_output_tokens": 256,
    }
    values.update(overrides)
    return GenerateRequest(**values)


# ------------------------------------------------------------------------- Gemini


def gemini_ok(_: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": '{"summary": "ok"}'}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 12,
                "candidatesTokenCount": 5,
                "totalTokenCount": 17,
            },
            "modelVersion": "test-model-002",
            "responseId": "resp-123",
        },
    )


async def test_gemini_generate_uses_native_json_schema_and_images() -> None:
    recorder = Recorder(gemini_ok)
    provider = GeminiProvider(api_key="gem-key", http_client=client(recorder))
    image = ImageInput(data=solid_png((255, 0, 0)), mime_type="image/png")

    response = await provider.generate(structured_request(images=[image]))

    request = recorder.requests[-1]
    assert request.url.path.endswith("/models/test-model:generateContent")
    assert request.headers["x-goog-api-key"] == "gem-key"
    body = recorder.body()
    config = body["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseJsonSchema"] == SCHEMA
    assert config["maxOutputTokens"] == 256
    assert body["systemInstruction"]["parts"][0]["text"] == "Be brief."
    parts = body["contents"][0]["parts"]
    # google-genai 3.x serialises inline data fields in snake_case.
    assert parts[0]["inlineData"]["mime_type"] == "image/png"
    assert parts[0]["inlineData"]["data"]
    assert parts[-1]["text"] == "Summarise."
    assert response.text == '{"summary": "ok"}'
    assert response.actual_model == "test-model-002"
    assert response.request_id == "resp-123"
    assert response.usage.input_tokens == 12 and response.usage.total_tokens == 17


async def test_gemini_list_models_keeps_generate_content_models() -> None:
    recorder = Recorder(
        lambda _: httpx2.Response(
            200,
            json={
                "models": [
                    {
                        "name": "models/gemini-test-flash",
                        "displayName": "Gemini Test Flash",
                        "supportedGenerationMethods": ["generateContent", "countTokens"],
                        "inputTokenLimit": 1048576,
                        "outputTokenLimit": 65536,
                    },
                    {
                        "name": "models/text-embedding-test",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                ]
            },
        )
    )
    models = await GeminiProvider(api_key="k", http_client=client(recorder)).list_models()
    assert [m.model_id for m in models] == ["gemini-test-flash"]
    assert models[0].input_token_limit == 1048576
    assert models[0].capabilities[Capability.TEXT].status == CapabilityStatus.SUPPORTED
    # Gemini's listing says nothing about vision: it must stay unknown, not assumed.
    assert models[0].capabilities[Capability.VISION].status == CapabilityStatus.UNKNOWN


def gemini_error(status: int, body: dict[str, Any]) -> Handler:
    return lambda _: httpx2.Response(status, json={"error": body})


@pytest.mark.parametrize(
    ("status", "body", "expected", "retry_after"),
    [
        (
            429,
            {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "Quota exceeded",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}
                        ],
                    }
                ],
            },
            AIQuotaExhaustedError,
            None,
        ),
        (
            429,
            {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "Quota exceeded",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}
                        ],
                    },
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "32s"},
                ],
            },
            AIRateLimitError,
            32.0,
        ),
        (
            400,
            {
                "code": 400,
                "status": "INVALID_ARGUMENT",
                "message": "API key not valid. Please pass a valid API key.",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": "API_KEY_INVALID",
                    }
                ],
            },
            AIAuthError,
            None,
        ),
        (
            503,
            {"code": 503, "status": "UNAVAILABLE", "message": "overloaded"},
            AIUnavailableError,
            None,
        ),
    ],
)
async def test_gemini_error_mapping(
    status: int, body: dict[str, Any], expected: type[Exception], retry_after: float | None
) -> None:
    provider = GeminiProvider(api_key="k", http_client=client(Recorder(gemini_error(status, body))))
    with pytest.raises(expected) as info:
        await provider.generate(structured_request())
    assert getattr(info.value, "retry_after", None) == retry_after


async def test_gemini_safety_block_is_reported() -> None:
    recorder = Recorder(
        lambda _: httpx2.Response(
            200, json={"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []}
        )
    )
    with pytest.raises(AIContentFilteredError):
        await GeminiProvider(api_key="k", http_client=client(recorder)).generate(
            structured_request()
        )


# ---------------------------------------------------------------------- Anthropic


def anthropic_ok(_: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(
        200,
        headers={"request-id": "req_abc"},
        json={
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-test-1",
            "content": [{"type": "text", "text": '{"summary": "ok"}'}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 20, "output_tokens": 6},
        },
    )


async def test_anthropic_generate_uses_output_config_and_image_blocks() -> None:
    recorder = Recorder(anthropic_ok)
    provider = AnthropicProvider(api_key="ant-key", http_client=client(recorder))
    image = ImageInput(data=solid_png((0, 0, 255)), mime_type="image/png")

    response = await provider.generate(structured_request(images=[image]))

    request = recorder.requests[-1]
    assert request.url.path.endswith("/v1/messages")
    # anthropic 2.x sends the API key as a bearer token.
    assert request.headers["authorization"] == "Bearer ant-key"
    assert request.headers["anthropic-version"]
    body = recorder.body()
    assert body["output_config"] == {"format": {"type": "json_schema", "schema": SCHEMA}}
    assert body["system"] == "Be brief."
    assert body["max_tokens"] == 256
    content = body["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/png"
    assert content[-1] == {"type": "text", "text": "Summarise."}
    assert "temperature" not in body
    assert response.actual_model == "claude-test-1"
    assert response.usage.total_tokens == 26


async def test_anthropic_prompt_mode_when_structured_output_unsupported() -> None:
    recorder = Recorder(anthropic_ok)
    provider = AnthropicProvider(api_key="k", http_client=client(recorder))
    await provider.generate(structured_request(native_structured_output=False))
    body = recorder.body()
    assert "output_config" not in body
    assert "JSON Schema" in body["messages"][0]["content"][-1]["text"]


async def test_anthropic_models_report_capabilities_from_metadata() -> None:
    recorder = Recorder(
        lambda _: httpx2.Response(
            200,
            json={
                "data": [
                    {
                        "type": "model",
                        "id": "claude-test-1",
                        "display_name": "Claude Test",
                        "created_at": "2026-01-01T00:00:00Z",
                        "max_input_tokens": 200000,
                        "max_tokens": 64000,
                        "capabilities": {
                            "image_input": {"supported": True},
                            "structured_outputs": {"supported": False},
                        },
                    }
                ],
                "has_more": False,
                "first_id": "claude-test-1",
                "last_id": "claude-test-1",
            },
        )
    )
    models = await AnthropicProvider(api_key="k", http_client=client(recorder)).list_models()
    assert models[0].model_id == "claude-test-1"
    assert models[0].capabilities[Capability.VISION].status == CapabilityStatus.SUPPORTED
    assert (
        models[0].capabilities[Capability.STRUCTURED_OUTPUT].status == CapabilityStatus.UNSUPPORTED
    )
    assert models[0].input_token_limit == 200000


@pytest.mark.parametrize(
    ("status", "error_type", "headers", "expected"),
    [
        (401, "authentication_error", {}, AIAuthError),
        (429, "rate_limit_error", {"retry-after": "7"}, AIRateLimitError),
        (529, "overloaded_error", {}, AIUnavailableError),
    ],
)
async def test_anthropic_error_mapping(
    status: int, error_type: str, headers: dict[str, str], expected: type[Exception]
) -> None:
    recorder = Recorder(
        lambda _: httpx2.Response(
            status,
            headers=headers,
            json={"type": "error", "error": {"type": error_type, "message": "nope"}},
        )
    )
    with pytest.raises(expected) as info:
        await AnthropicProvider(api_key="k", http_client=client(recorder)).generate(
            structured_request()
        )
    if expected is AIRateLimitError:
        assert info.value.retry_after == 7  # type: ignore[attr-defined]


# ------------------------------------------------------------------------- OpenAI


def openai_ok(_: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 1,
            "model": "gpt-test-2026",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": '{"summary": "ok"}'},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13},
        },
    )


async def test_openai_generate_uses_json_schema_response_format() -> None:
    recorder = Recorder(openai_ok)
    provider = OpenAIProvider(api_key="oa-key", http_client=client(recorder))
    image = ImageInput(data=solid_png((0, 255, 0)), mime_type="image/png")

    response = await provider.generate(structured_request(images=[image]))

    request = recorder.requests[-1]
    assert request.url.path.endswith("/chat/completions")
    assert request.headers["authorization"] == "Bearer oa-key"
    body = recorder.body()
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == SCHEMA
    assert body["response_format"]["json_schema"]["name"] == "Summary"
    assert body["max_completion_tokens"] == 256
    assert body["messages"][0] == {"role": "system", "content": "Be brief."}
    user_content = body["messages"][1]["content"]
    assert user_content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert response.actual_model == "gpt-test-2026"
    assert response.usage.total_tokens == 13


async def test_openai_list_hides_non_chat_models() -> None:
    recorder = Recorder(
        lambda _: httpx2.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"id": "gpt-test-2026", "object": "model", "created": 1, "owned_by": "openai"},
                    {
                        "id": "text-embedding-3-small",
                        "object": "model",
                        "created": 1,
                        "owned_by": "openai",
                    },
                    {"id": "whisper-1", "object": "model", "created": 1, "owned_by": "openai"},
                ],
            },
        )
    )
    models = await OpenAIProvider(api_key="k", http_client=client(recorder)).list_models()
    assert [m.model_id for m in models] == ["gpt-test-2026"]
    assert all(v.status == CapabilityStatus.UNKNOWN for k, v in models[0].capabilities.items())


@pytest.mark.parametrize(
    ("status", "error", "expected"),
    [
        (
            401,
            {"message": "bad key", "type": "invalid_request_error", "code": "invalid_api_key"},
            AIAuthError,
        ),
        (
            429,
            {"message": "quota", "type": "insufficient_quota", "code": "insufficient_quota"},
            AIQuotaExhaustedError,
        ),
        (
            429,
            {"message": "slow down", "type": "requests", "code": "rate_limit_exceeded"},
            AIRateLimitError,
        ),
        (500, {"message": "boom", "type": "server_error", "code": None}, AIUnavailableError),
    ],
)
async def test_openai_error_mapping(
    status: int, error: dict[str, Any], expected: type[Exception]
) -> None:
    recorder = Recorder(lambda _: httpx2.Response(status, json={"error": error}))
    with pytest.raises(expected):
        await OpenAIProvider(api_key="k", http_client=client(recorder)).generate(
            structured_request()
        )


async def test_gemini_retired_model_is_explained() -> None:
    """Seen live: models.list still returns gemini-2.5-flash, generate_content rejects it."""
    body = {
        "code": 404,
        "status": "NOT_FOUND",
        "message": "This model models/gemini-2.5-flash is no longer available to new users.",
    }
    provider = GeminiProvider(api_key="k", http_client=client(Recorder(gemini_error(404, body))))
    with pytest.raises(AIModelNotFoundError) as info:
        await provider.generate(structured_request())
    assert "listed but not available to your key" in info.value.message


async def test_gemini_schema_drops_array_bounds() -> None:
    """Seen live: Gemini rejects responseJsonSchema containing minItems/maxItems."""
    recorder = Recorder(gemini_ok)
    provider = GeminiProvider(api_key="k", http_client=client(recorder))
    schema = {
        "type": "object",
        "properties": {
            "steps": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 100}
        },
        "required": ["steps"],
    }
    request = structured_request()
    await provider.generate(replace(request, json_schema=schema))
    sent = recorder.body()["generationConfig"]["responseJsonSchema"]
    assert sent["properties"]["steps"] == {"type": "array", "items": {"type": "string"}}


async def test_openai_compatible_providers_use_their_endpoint_and_parameters() -> None:
    from app.services.ai.providers.openai_compatible import DeepSeekProvider, OllamaProvider

    recorder = Recorder(openai_ok)
    deepseek = DeepSeekProvider(api_key="ds-key", http_client=client(recorder))
    await deepseek.generate(structured_request())
    request = recorder.requests[-1]
    assert request.url.host == "api.deepseek.com"
    assert request.headers["authorization"] == "Bearer ds-key"
    body = recorder.body()
    assert body["max_tokens"] == 256 and "max_completion_tokens" not in body
    # DeepSeek has JSON mode but no JSON Schema: the schema travels in the prompt instead.
    assert body["response_format"] == {"type": "json_object"}
    assert '"summary"' in body["messages"][-1]["content"][0]["text"]

    local = Recorder(openai_ok)
    ollama = OllamaProvider(api_key=None, http_client=client(local))
    await ollama.generate(structured_request())
    assert str(local.requests[-1].url).startswith("http://localhost:11434/v1/")
    assert local.body()["response_format"]["type"] == "json_schema"


async def test_openai_compatible_errors_name_the_provider() -> None:
    from app.services.ai.providers.openai_compatible import MistralProvider

    def unauthorized(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401, json={"error": {"message": "bad key", "type": "auth"}})

    provider = MistralProvider(api_key="k", http_client=client(Recorder(unauthorized)))
    with pytest.raises(AIAuthError, match=r"^Mistral rejected the API key"):
        await provider.generate(structured_request())
