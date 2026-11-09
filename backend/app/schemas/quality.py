from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.failure import FailureAnalysisOutput


class EvidenceItem(BaseModel):
    id: str
    kind: str
    title: str
    detail: str


class FailureAnalysisOut(BaseModel):
    id: uuid.UUID
    execution_id: uuid.UUID
    test_case_id: uuid.UUID | None
    test_version_id: uuid.UUID | None
    failed_step_index: int | None
    status: Literal["completed", "failed"]
    evidence: list[EvidenceItem] = Field(description="Verified facts collected from the run.")
    used_screenshot: bool
    result: FailureAnalysisOutput | None = Field(description="AI output: hypotheses, not facts.")
    ai_request_ids: list[str]
    error_code: str | None
    error_message: str | None
    created_at: datetime


class DiffRow(BaseModel):
    kind: Literal["same", "changed", "added", "removed"]
    index: int | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None = None


class ProposalIssue(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    step: int | None = None


class RepairProposalOut(BaseModel):
    id: uuid.UUID
    analysis_id: uuid.UUID
    test_case_id: uuid.UUID
    base_version_id: uuid.UUID | None
    status: Literal["proposed", "no_change", "invalid", "approved", "rejected", "superseded"]
    verdict: Literal["fix_test", "no_test_change"]
    rationale: str
    diff: list[DiffRow]
    issues: list[ProposalIssue]
    ai_request_ids: list[str]
    resulting_version_id: uuid.UUID | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime


class FailureReviewOut(BaseModel):
    analysis: FailureAnalysisOut | None
    proposals: list[RepairProposalOut]


class RejectIn(BaseModel):
    note: str = Field(default="", max_length=1000)


class ApprovalOut(BaseModel):
    proposal: RepairProposalOut
    version_id: uuid.UUID
    version: int


class RollbackOut(BaseModel):
    test_case_id: uuid.UUID
    current_version_id: uuid.UUID
    version: int
