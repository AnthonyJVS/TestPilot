"""Provider registry: the catalog shown in the UI and the factory used by the orchestrator."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from app.services.ai.base import AIProvider

ProviderStatus = Literal["available", "planned"]
BaseUrlMode = Literal["none", "optional", "required"]
DataLocation = Literal["external", "local"]


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    type_id: str
    display_name: str
    description: str
    status: ProviderStatus
    data_location: DataLocation
    requires_api_key: bool = True
    base_url_mode: BaseUrlMode = "none"
    supports_model_listing: bool = True
    key_help_url: str | None = None
    milestone: int | None = None
    factory: Callable[..., AIProvider] | None = None


def _gemini(**kwargs: Any) -> AIProvider:
    from app.services.ai.providers.gemini import GeminiProvider

    return GeminiProvider(**kwargs)


def _anthropic(**kwargs: Any) -> AIProvider:
    from app.services.ai.providers.anthropic import AnthropicProvider

    return AnthropicProvider(**kwargs)


def _openai(**kwargs: Any) -> AIProvider:
    from app.services.ai.providers.openai import OpenAIProvider

    return OpenAIProvider(**kwargs)


# Planned integrations (milestone 8). Listed so the UI can show them honestly as unavailable.
_PLANNED: tuple[tuple[str, str, str, DataLocation], ...] = (
    ("deepseek", "DeepSeek", "DeepSeek API.", "external"),
    ("mistral", "Mistral AI", "Mistral API.", "external"),
    ("xai", "xAI Grok", "xAI API.", "external"),
    ("openrouter", "OpenRouter", "Many models through one OpenRouter key.", "external"),
    ("azure_openai", "Azure OpenAI", "OpenAI models deployed in your Azure tenant.", "external"),
    ("aws_bedrock", "AWS Bedrock", "Models hosted in your AWS account.", "external"),
    ("ollama", "Ollama", "Models running on your own machine.", "local"),
    ("lmstudio", "LM Studio", "Models served locally by LM Studio.", "local"),
)

DEFAULT_SPECS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        type_id="gemini",
        display_name="Google Gemini",
        description="Gemini Developer API. One free-tier key can run every supported task.",
        status="available",
        data_location="external",
        key_help_url="https://aistudio.google.com/apikey",
        factory=_gemini,
    ),
    ProviderSpec(
        type_id="anthropic",
        display_name="Anthropic Claude",
        description="Claude models through the Anthropic API.",
        status="available",
        data_location="external",
        key_help_url="https://console.anthropic.com/settings/keys",
        factory=_anthropic,
    ),
    ProviderSpec(
        type_id="openai",
        display_name="OpenAI",
        description="GPT models through the OpenAI API.",
        status="available",
        data_location="external",
        base_url_mode="optional",
        key_help_url="https://platform.openai.com/api-keys",
        factory=_openai,
    ),
    *(
        ProviderSpec(
            type_id=type_id,
            display_name=name,
            description=description,
            status="planned",
            data_location=location,
            requires_api_key=location == "external",
            milestone=8,
        )
        for type_id, name, description, location in _PLANNED
    ),
)


class UnknownProviderTypeError(KeyError):
    pass


class ProviderRegistry:
    def __init__(self, specs: tuple[ProviderSpec, ...] = DEFAULT_SPECS) -> None:
        self._specs: dict[str, ProviderSpec] = {spec.type_id: spec for spec in specs}

    def register(self, spec: ProviderSpec) -> None:
        self._specs[spec.type_id] = spec

    def all(self) -> list[ProviderSpec]:
        return list(self._specs.values())

    def get(self, type_id: str) -> ProviderSpec:
        try:
            return self._specs[type_id]
        except KeyError as exc:
            raise UnknownProviderTypeError(type_id) from exc

    def create(
        self,
        type_id: str,
        *,
        api_key: str | None,
        base_url: str | None,
        config: dict[str, Any],
        timeout_seconds: float,
    ) -> AIProvider:
        spec = self.get(type_id)
        if spec.status != "available" or spec.factory is None:
            raise UnknownProviderTypeError(f"{type_id} is not available yet")
        return spec.factory(
            api_key=api_key, base_url=base_url, config=config, timeout_seconds=timeout_seconds
        )
