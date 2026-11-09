from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ExecutionStatus = Literal["queued", "running", "passed", "failed", "error", "cancelled"]
StepStatus = Literal["pending", "running", "passed", "failed", "skipped"]
Browser = Literal["chromium", "firefox", "webkit"]


class RunCreate(BaseModel):
    environment_id: uuid.UUID | None = Field(
        default=None, description="Defaults to the project's default environment."
    )
    browser: Browser = "chromium"
    screenshots: Literal["every_step", "on_failure", "off"] = "every_step"
    trace: bool = True
    video: bool = False


class ExecutionStepOut(BaseModel):
    index: int
    action: str
    description: str
    status: StepStatus
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    url: str | None
    error_code: str | None
    error_message: str | None


class ArtifactOut(BaseModel):
    id: uuid.UUID
    kind: Literal["screenshot", "trace", "video", "network_log", "console_log"]
    name: str
    content_type: str
    size_bytes: int
    step_index: int | None
    created_at: datetime


class TestExecutionOut(BaseModel):
    id: uuid.UUID
    test_case_id: uuid.UUID | None
    test_version_id: uuid.UUID | None
    environment_id: uuid.UUID | None
    test_name: str
    version_number: int
    environment_name: str
    base_url: str
    browser: Browser
    browser_version: str | None
    status: ExecutionStatus
    steps_total: int
    steps_passed: int
    steps_failed: int
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    steps: list[ExecutionStepOut]


class ExecutionSummaryOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    kind: Literal["test_run"]
    status: ExecutionStatus
    test_case_id: uuid.UUID | None
    test_name: str
    version_number: int
    environment_name: str
    browser: Browser
    steps_total: int
    steps_passed: int
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None


class ExecutionOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    kind: Literal["test_run"]
    status: ExecutionStatus
    trigger: str
    error_code: str | None
    error_message: str | None
    cancel_requested: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    isolated: bool = Field(description="True when the browser ran in the isolated worker.")
    notes: list[str]
    capture: dict[str, Any]
    test: TestExecutionOut
    artifacts: list[ArtifactOut]


class ExecutionEventOut(BaseModel):
    seq: int
    ts: datetime
    type: str
    category: str
    level: Literal["info", "warning", "error"]
    node_id: str | None
    step_index: int | None
    message: str
    data: dict[str, Any]


class ExecutionRuntimeOut(BaseModel):
    mode: Literal["inline", "celery"]
    transport: Literal["thread", "redis"]
    isolated: bool
    available: bool
    detail: str | None
    playwright_version: str | None
    browsers: dict[str, bool]
    allow_private_network: bool
    max_run_seconds: int
