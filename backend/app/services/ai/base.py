"""Adapter contract every provider implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from app.services.ai.types import ConnectionCheck, GenerateRequest, GenerateResponse, ModelInfo

# Instruction appended when a model has no native JSON-schema mode.
JSON_ONLY_INSTRUCTION = (
    "Respond with a single JSON object only, with no markdown fences or commentary. "
    "It must conform to this JSON Schema:\n"
)


class AIProvider(ABC):
    type_id: ClassVar[str]

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str | None = None,
        config: dict[str, Any] | None = None,
        http_client: Any = None,
        timeout_seconds: float = 90.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.config = config or {}
        self.http_client = http_client
        self.timeout_seconds = timeout_seconds

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """Models usable for text generation (AINotSupportedError if listing is unavailable)."""

    @abstractmethod
    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        """One call to the provider. Must raise only ``AIProviderError`` subclasses."""

    async def validate_connection(self) -> ConnectionCheck:
        """Default: listing models proves the key works without spending generation quota."""
        models = await self.list_models()
        return ConnectionCheck(
            ok=True, message=f"Connected. {len(models)} models available.", model_count=len(models)
        )

    async def aclose(self) -> None:  # noqa: B027 - optional hook
        """Release network resources."""
