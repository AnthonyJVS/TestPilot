"""Providers that speak the OpenAI Chat Completions API (milestone 8).

They reuse the OpenAI adapter with their own endpoint, label and capability switches. They are
implemented against each provider's published OpenAI-compatible API and covered by mock-HTTP
tests, but have not been exercised with live keys: the UI marks them "unverified" until they are.
"""

from __future__ import annotations

from app.services.ai.providers.openai import OpenAIProvider


class DeepSeekProvider(OpenAIProvider):
    type_id = "deepseek"
    label = "DeepSeek"
    default_base_url = "https://api.deepseek.com"
    max_tokens_param = "max_tokens"
    json_schema_supported = False  # JSON mode only; the schema goes into the prompt


class MistralProvider(OpenAIProvider):
    type_id = "mistral"
    label = "Mistral"
    default_base_url = "https://api.mistral.ai/v1"
    max_tokens_param = "max_tokens"


class XAIProvider(OpenAIProvider):
    type_id = "xai"
    label = "xAI"
    default_base_url = "https://api.x.ai/v1"
    max_tokens_param = "max_tokens"


class OpenRouterProvider(OpenAIProvider):
    type_id = "openrouter"
    label = "OpenRouter"
    default_base_url = "https://openrouter.ai/api/v1"
    max_tokens_param = "max_tokens"


class OllamaProvider(OpenAIProvider):
    type_id = "ollama"
    label = "Ollama"
    default_base_url = "http://localhost:11434/v1"
    max_tokens_param = "max_tokens"
    placeholder_api_key = "ollama"


class LMStudioProvider(OpenAIProvider):
    type_id = "lmstudio"
    label = "LM Studio"
    default_base_url = "http://localhost:1234/v1"
    max_tokens_param = "max_tokens"
    placeholder_api_key = "lm-studio"
