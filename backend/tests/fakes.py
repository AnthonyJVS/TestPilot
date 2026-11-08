"""A scriptable in-memory AI provider for API/orchestrator tests (never used outside tests)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.services.ai.base import AIProvider
from app.services.ai.errors import AIProviderError
from app.services.ai.registry import DEFAULT_SPECS, ProviderRegistry, ProviderSpec
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

# Valid answers for each routing-check schema.
CHECK_ANSWERS: dict[str, dict[str, Any]] = {
    "RequirementList": {"requirements": ["Login page opens", "Dashboard greets the user"]},
    "StepList": {
        "steps": [
            {"action": "fill", "target": "search box"},
            {"action": "expect", "target": "results list"},
        ]
    },
    "CodeSnippet": {"code": 'page.get_by_role("button", name="Sign in").click()'},
    "FailureClassification": {"category": "timeout", "summary": "Submit button never appeared."},
    "ColourAnswer": {"colour": "red"},
    "LocatorProposal": {"locator": 'page.get_by_role("button", name="Log in")'},
    "OneLineSummary": {"summary": "Three tests passed; checkout total mismatch failed."},
    "RequirementAnalysis": {
        "summary": "A registered user signs in and sees the dashboard.",
        "requirements": [
            "The login page opens",
            "Valid credentials sign the user in",
            "The dashboard greets the user",
        ],
        "test_data": [
            {"name": "LOGIN_EMAIL", "kind": "env", "description": "Test account email"},
            {"name": "LOGIN_PASSWORD", "kind": "secret", "description": "Test account password"},
        ],
        "ambiguities": [],
    },
    "TestPlan": {
        "name": "Sign in and see the dashboard",
        "description": "A registered user signs in.",
        "preconditions": ["A test account exists"],
        "test_data": [
            {"name": "LOGIN_EMAIL", "kind": "env", "description": "Test account email"},
            {"name": "LOGIN_PASSWORD", "kind": "secret", "description": "Test account password"},
        ],
        "steps": [
            {"action": "goto", "description": "Open the login page", "value": "/login"},
            {
                "action": "fill",
                "description": "Enter the email",
                "locator": {"strategy": "label", "value": "Email"},
                "value": "{{env.LOGIN_EMAIL}}",
            },
            {
                "action": "fill",
                "description": "Enter the password",
                "locator": {"strategy": "label", "value": "Password"},
                "value": "{{secret.LOGIN_PASSWORD}}",
            },
            {
                "action": "click",
                "description": "Sign in",
                "locator": {"strategy": "role", "role": "button", "value": "Sign in"},
            },
            {"action": "expect_url", "description": "Dashboard opens", "value": "/dashboard"},
        ],
        "expected_results": ["The dashboard is shown"],
        "cleanup": [],
    },
}


@dataclass
class Call:
    provider_type: str
    api_key: str | None
    request: GenerateRequest


@dataclass
class FakeState:
    calls: list[Call] = field(default_factory=list)
    # Queued outcomes per provider type: a GenerateResponse, raw JSON text, or an exception.
    script: dict[str, list[Any]] = field(default_factory=dict)
    models: dict[str, list[ModelInfo]] = field(default_factory=dict)
    list_errors: dict[str, AIProviderError] = field(default_factory=dict)


def vision_model(model_id: str, vision: CapabilityStatus) -> ModelInfo:
    capabilities = unknown_capabilities()
    capabilities[Capability.TEXT] = CapabilityValue(
        CapabilityStatus.SUPPORTED, CapabilitySource.PROVIDER_METADATA
    )
    capabilities[Capability.VISION] = CapabilityValue(vision, CapabilitySource.PROVIDER_METADATA)
    return ModelInfo(model_id=model_id, display_name=model_id.title(), capabilities=capabilities)


class FakeProvider(AIProvider):
    state: ClassVar[FakeState] = FakeState()
    type_id = "fake"

    def __init__(self, provider_type: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.provider_type = provider_type

    async def list_models(self) -> list[ModelInfo]:
        if self.provider_type in self.state.list_errors:
            raise self.state.list_errors[self.provider_type]
        return self.state.models.get(
            self.provider_type,
            [
                vision_model(f"{self.provider_type}-pro", CapabilityStatus.UNKNOWN),
                vision_model(f"{self.provider_type}-text", CapabilityStatus.UNSUPPORTED),
            ],
        )

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.state.calls.append(Call(self.provider_type, self.api_key, request))
        queue = self.state.script.get(self.provider_type, [])
        outcome: Any = queue.pop(0) if queue else CHECK_ANSWERS.get(request.schema_name, {})
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, GenerateResponse):
            return outcome
        text = outcome if isinstance(outcome, str) else json.dumps(outcome)
        return GenerateResponse(
            text=text,
            actual_model=f"{request.model}-001",
            request_id=f"req-{len(self.state.calls)}",
            usage=TokenUsage(input_tokens=11, output_tokens=7, total_tokens=18),
            finish_reason="stop",
        )


def fake_registry() -> ProviderRegistry:
    registry = ProviderRegistry(DEFAULT_SPECS)
    for type_id, name in (("fake", "Fake AI"), ("fake2", "Second Fake AI")):
        registry.register(
            ProviderSpec(
                type_id=type_id,
                display_name=name,
                description="Test double",
                status="available",
                data_location="external",
                factory=lambda type_id=type_id, **kw: FakeProvider(type_id, **kw),
            )
        )
    return registry
