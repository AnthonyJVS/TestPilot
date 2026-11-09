from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.domain.workflow import GraphIssue, WorkflowGraph


class PortOut(BaseModel):
    name: str
    type: str
    label: str
    required: bool
    multi: bool


class NodeTypeOut(BaseModel):
    type: str
    version: int
    category: Literal["data", "browser", "test", "ai", "logic"]
    label: str
    description: str
    available: bool
    milestone: int | None
    entry: bool
    inputs: list[PortOut]
    outputs: list[PortOut]
    config_schema: dict[str, Any]
    defaults: dict[str, Any]


def _clean(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("Must not be blank.")
    return value


Template = Literal["blank", "run_test", "generate_and_run"]


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    template: Template = "blank"
    test_case_id: uuid.UUID | None = Field(
        default=None, description="Used by the run_test template."
    )

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean(value)


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class GraphIn(BaseModel):
    graph: WorkflowGraph


class VersionSummary(BaseModel):
    id: uuid.UUID
    version: int
    created_at: datetime


class WorkflowVersionOut(BaseModel):
    id: uuid.UUID
    version: int
    graph: WorkflowGraph
    issues: list[GraphIssue]
    created_at: datetime


class WorkflowSummaryOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    name: str
    description: str
    latest_version: int
    nodes: int
    updated_at: datetime
    last_run_status: str | None
    last_run_at: datetime | None


class WorkflowOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str
    latest: WorkflowVersionOut
    versions: list[VersionSummary]
    created_at: datetime
    updated_at: datetime


class ValidationOut(BaseModel):
    issues: list[GraphIssue]
    runnable: bool


class WorkflowRunCreate(BaseModel):
    version: int | None = Field(default=None, description="Defaults to the latest version.")
