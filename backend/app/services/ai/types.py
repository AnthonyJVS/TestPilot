"""Provider-agnostic contracts for AI operations. No SDK types appear here."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TaskCategory(StrEnum):
    REQUIREMENT_ANALYSIS = "requirement_analysis"
    TEST_PLANNING = "test_planning"
    CODE_GENERATION = "code_generation"
    FAILURE_ANALYSIS = "failure_analysis"
    VISUAL_ANALYSIS = "visual_analysis"
    TEST_REPAIR = "test_repair"
    REPORT_GENERATION = "report_generation"


TASK_LABELS: dict[TaskCategory, str] = {
    TaskCategory.REQUIREMENT_ANALYSIS: "Requirement analysis",
    TaskCategory.TEST_PLANNING: "Test planning",
    TaskCategory.CODE_GENERATION: "Code generation",
    TaskCategory.FAILURE_ANALYSIS: "Failure analysis",
    TaskCategory.VISUAL_ANALYSIS: "Visual analysis",
    TaskCategory.TEST_REPAIR: "Test repair",
    TaskCategory.REPORT_GENERATION: "Report generation",
}


class Capability(StrEnum):
    TEXT = "text"
    STRUCTURED_OUTPUT = "structured_output"
    VISION = "vision"
    TOOL_CALLING = "tool_calling"


class CapabilityStatus(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class CapabilitySource(StrEnum):
    PROVIDER_METADATA = "provider_metadata"  # reported by the provider's model listing API
    PROBE = "probe"  # verified by a real call (routing check)
    NONE = "none"


# Capabilities each task needs beyond text + structured output.
TASK_REQUIREMENTS: dict[TaskCategory, tuple[Capability, ...]] = {
    TaskCategory.VISUAL_ANALYSIS: (Capability.VISION,),
}


@dataclass(frozen=True, slots=True)
class CapabilityValue:
    status: CapabilityStatus
    source: CapabilitySource = CapabilitySource.NONE

    def to_json(self) -> dict[str, str]:
        return {"status": self.status.value, "source": self.source.value}


def unknown_capabilities() -> dict[Capability, CapabilityValue]:
    return {cap: CapabilityValue(CapabilityStatus.UNKNOWN) for cap in Capability}


@dataclass(slots=True)
class ModelInfo:
    model_id: str
    display_name: str
    capabilities: dict[Capability, CapabilityValue] = field(default_factory=unknown_capabilities)
    input_token_limit: int | None = None
    output_token_limit: int | None = None


@dataclass(frozen=True, slots=True)
class ImageInput:
    data: bytes
    mime_type: str


@dataclass(slots=True)
class GenerateRequest:
    model: str
    prompt: str
    system: str | None = None
    images: list[ImageInput] = field(default_factory=list)
    temperature: float | None = None
    max_output_tokens: int = 4096
    timeout_seconds: float = 90.0
    # When set, the provider is asked for JSON matching this schema (native mode if available).
    json_schema: dict[str, Any] | None = None
    schema_name: str = "result"
    native_structured_output: bool = True


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class GenerateResponse:
    text: str
    actual_model: str | None
    request_id: str | None
    usage: TokenUsage
    finish_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ConnectionCheck:
    ok: bool
    message: str
    model_count: int | None = None
