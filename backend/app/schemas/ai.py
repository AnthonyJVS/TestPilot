from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.services.ai.types import TaskCategory

RouteSource = Literal["override", "task_route", "default"]


# ------------------------------------------------------------------ provider catalog


class ProviderTypeOut(BaseModel):
    type_id: str
    display_name: str
    description: str
    status: Literal["available", "planned"]
    data_location: Literal["external", "local"]
    requires_api_key: bool
    base_url_mode: Literal["none", "optional", "required"]
    supports_model_listing: bool
    key_help_url: str | None
    milestone: int | None
    verified: bool
    default_base_url: str | None


# ---------------------------------------------------------------------- connections


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class ProviderCreate(BaseModel):
    provider_type: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=100)
    api_key: SecretStr | None = Field(default=None, max_length=500)
    base_url: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Name must not be blank.")
        return value

    @field_validator("base_url")
    @classmethod
    def _base_url(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return " ".join(value.split()) if value else value


class CredentialUpdate(BaseModel):
    api_key: SecretStr = Field(min_length=8, max_length=500)


class CapabilityOut(BaseModel):
    status: Literal["supported", "unsupported", "unknown"]
    source: Literal["provider_metadata", "probe", "none"]


class ModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider_id: uuid.UUID
    model_id: str
    display_name: str
    source: Literal["discovered", "manual"]
    capabilities: dict[str, CapabilityOut]
    input_token_limit: int | None
    output_token_limit: int | None
    listed_by_provider: bool


class ModelCreate(BaseModel):
    model_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:/@+-]+$")
    display_name: str | None = Field(default=None, max_length=200)


class CredentialOut(BaseModel):
    key_hint: str
    created_at: datetime
    rotated_at: datetime | None


class ProviderOut(BaseModel):
    id: uuid.UUID
    provider_type: str
    provider_display_name: str
    data_location: Literal["external", "local"]
    name: str
    base_url: str | None
    status: Literal["untested", "connected", "error"]
    last_validated_at: datetime | None
    last_error: str | None
    credential: CredentialOut | None
    models: list[ModelOut]
    created_at: datetime


class ConnectionTestOut(BaseModel):
    ok: bool
    message: str
    model_count: int | None
    provider: ProviderOut


# -------------------------------------------------------------------------- routing


class RoutingUpdate(BaseModel):
    mode: Literal["simple", "advanced"]
    default_model_id: uuid.UUID | None = None
    task_routes: dict[TaskCategory, uuid.UUID | None] = Field(default_factory=dict)
    fallback_enabled: bool = False
    fallback_model_id: uuid.UUID | None = None
    daily_request_limit: int | None = Field(default=None, ge=1, le=100_000)
    store_payload_previews: bool = True


class RouteModelOut(BaseModel):
    model_configuration_id: uuid.UUID
    model_id: str
    display_name: str
    provider_id: uuid.UUID
    provider_name: str
    provider_type: str
    data_location: Literal["external", "local"]


class EffectiveRouteOut(BaseModel):
    task: TaskCategory
    label: str
    source: RouteSource | None
    model: RouteModelOut | None
    required_capabilities: list[str]
    issues: list[str]
    warnings: list[str]


class RoutingOut(BaseModel):
    mode: Literal["simple", "advanced"]
    default_model_id: uuid.UUID | None
    task_routes: dict[str, uuid.UUID]
    fallback_enabled: bool
    fallback_model_id: uuid.UUID | None
    daily_request_limit: int | None
    store_payload_previews: bool
    requests_today: int
    effective: list[EffectiveRouteOut]


class TaskCheckOut(BaseModel):
    task: TaskCategory
    label: str
    status: Literal["passed", "failed", "error"]
    message: str
    provider_type: str | None
    model: str | None
    actual_model: str | None
    latency_ms: int | None
    total_tokens: int | None
    ai_request_id: uuid.UUID | None


# ------------------------------------------------------------------- request log


class AIRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task: str | None
    origin: str
    route_source: str | None
    requested_provider_type: str
    requested_model: str
    actual_provider_type: str | None
    actual_model: str | None
    provider_request_id: str | None
    status: str
    error_code: str | None
    error_message: str | None
    attempts: int
    fallback_used: bool
    fallback_reason: str | None
    retry_history: list[dict[str, Any]]
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    latency_ms: int | None
    request_preview: dict[str, Any] | None
    response_preview: dict[str, Any] | None
    started_at: datetime
    finished_at: datetime | None


class AIRequestPage(BaseModel):
    items: list[AIRequestOut]
    next_cursor: str | None


class UsageDayOut(BaseModel):
    date: str
    requests: int
    succeeded: int
    failed: int
    tokens: int


class UsageModelOut(BaseModel):
    provider_type: str
    model: str
    requests: int
    failed: int
    tokens: int
    fallbacks: int
    avg_latency_ms: int | None
    p95_latency_ms: int | None


class UsageTaskOut(BaseModel):
    task: str
    requests: int
    tokens: int
    failed: int


class UsageTotalsOut(BaseModel):
    requests: int
    succeeded: int
    failed: int
    tokens: int
    fallbacks: int
    avg_latency_ms: int | None
    p95_latency_ms: int | None


class AIUsageOut(BaseModel):
    """Aggregates of the AI request log. Costs are not estimated: no dated price source."""

    days: list[UsageDayOut]
    models: list[UsageModelOut]
    tasks: list[UsageTaskOut]
    origins: dict[str, int]
    totals: UsageTotalsOut
    requests_today: int
    daily_limit: int | None
