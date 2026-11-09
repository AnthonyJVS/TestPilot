from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.test_plan import VARIABLE_NAME, TestDataRef, TestPlan

CaseStatus = Literal["draft", "planned", "approved"]


def _clean_name(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("Must not be blank.")
    return value


# ------------------------------------------------------------------- projects


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=2000)
    allowed_domains: list[str] | None = Field(default=None, max_length=20)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean_name(value)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    allowed_domains: list[str] | None = Field(default=None, max_length=20)


class VariableOut(BaseModel):
    name: str
    is_secret: bool
    value: str | None = Field(description="Always null for secrets: they are write-only.")
    has_value: bool
    updated_at: datetime


class VariableUpsert(BaseModel):
    value: str = Field(min_length=1, max_length=4000)
    is_secret: bool


class EnvironmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _-]*$")
    base_url: str | None = Field(default=None, max_length=500)
    is_default: bool = False


class EnvironmentUpdate(BaseModel):
    name: str | None = Field(
        default=None, min_length=1, max_length=60, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _-]*$"
    )
    base_url: str | None = Field(default=None, max_length=500)
    is_default: bool | None = None


class EnvironmentOut(BaseModel):
    id: uuid.UUID
    name: str
    base_url: str | None
    effective_base_url: str
    is_default: bool
    variables: list[VariableOut]


class ProjectSummaryOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    base_url: str
    suite_count: int
    case_count: int
    approved_count: int
    updated_at: datetime


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    base_url: str
    allowed_domains: list[str]
    environments: list[EnvironmentOut]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- suites/cases


class SuiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean_name(value)


class SuiteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class CaseSummaryOut(BaseModel):
    id: uuid.UUID
    suite_id: uuid.UUID
    name: str
    status: CaseStatus
    current_version: int | None
    updated_at: datetime


class SuiteOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    cases: list[CaseSummaryOut]


class CaseCreate(BaseModel):
    suite_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    scenario: str = Field(default="", max_length=8000)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean_name(value)


class CaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    scenario: str | None = Field(default=None, max_length=8000)
    suite_id: uuid.UUID | None = None


# ------------------------------------------------------------- plans/versions


class RequirementAnalysis(BaseModel):
    """AI output of the requirement-analysis step (shown to the reviewer as AI-produced)."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(description="One or two sentences describing what the test verifies.")
    requirements: list[str] = Field(description="Separate, testable requirements.")
    test_data: list[TestDataRef] = Field(
        description="Data the test needs, as environment variables (secret for passwords/tokens)."
    )
    ambiguities: list[str] = Field(
        description="Open questions a human should confirm. Empty if none."
    )


class PlanIssueOut(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    step: int | None


class AIRequestSummaryOut(BaseModel):
    id: uuid.UUID
    task: str | None
    status: str
    requested_provider_type: str
    requested_model: str
    actual_provider_type: str | None
    actual_model: str | None
    latency_ms: int | None
    total_tokens: int | None
    fallback_used: bool


class PlanOut(BaseModel):
    id: uuid.UUID
    revision: int
    source: Literal["ai", "manual", "edited", "repair"]
    status: Literal["draft", "approved"]
    plan: TestPlan
    analysis: RequirementAnalysis | None
    issues: list[PlanIssueOut]
    environment_name: str | None
    ai_requests: list[AIRequestSummaryOut]
    scenario_snapshot: str
    created_at: datetime
    updated_at: datetime


class PlanSave(BaseModel):
    plan: TestPlan


class PlanGenerate(BaseModel):
    environment_id: uuid.UUID | None = None


class VersionSummaryOut(BaseModel):
    id: uuid.UUID
    version: int
    created_at: datetime


class VersionOut(BaseModel):
    id: uuid.UUID
    test_case_id: uuid.UUID
    version: int
    plan: TestPlan
    base_url: str
    code_python: str
    code_typescript: str
    renderer_version: str
    created_at: datetime


class CaseOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    suite_id: uuid.UUID
    name: str
    scenario: str
    status: CaseStatus
    current_version_id: uuid.UUID | None
    latest_plan: PlanOut | None
    versions: list[VersionSummaryOut]
    created_at: datetime
    updated_at: datetime


VARIABLE_NAME_PATTERN = f"^{VARIABLE_NAME}$"
