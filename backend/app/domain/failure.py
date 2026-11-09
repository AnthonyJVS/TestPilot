"""Failure analysis and repair proposals (milestone 7).

Evidence is collected by TestPilot from the run itself and numbered (E1, E2, ...). The AI only
contributes an explanation and hypotheses that must cite evidence IDs; it never states facts
the UI would present as verified. Repairs are small, validated edits to the test plan that a
person must approve before they become a new version.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.test_plan import Step

EVIDENCE_ID = r"^E[0-9]{1,2}$"

FailureCategory = Literal[
    "locator_changed",
    "element_missing",
    "timing",
    "assertion_mismatch",
    "navigation",
    "network",
    "test_data",
    "environment",
    "application_bug",
    "unknown",
]
RecommendedAction = Literal[
    "repair_test", "report_bug", "retry", "fix_environment", "needs_more_information"
]


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1, max_length=500)
    confidence: Literal["low", "medium", "high"]
    evidence_ids: list[str] = Field(
        default_factory=list, max_length=10, description="Evidence items supporting it (E1...)."
    )

    @field_validator("evidence_ids")
    @classmethod
    def _ids(cls, values: list[str]) -> list[str]:
        return [v for v in values if re.match(EVIDENCE_ID, v)]


class FailureAnalysisOutput(BaseModel):
    """What the AI returns for a failure. Every hypothesis cites the evidence it rests on."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=600, description="Two or three sentences.")
    category: FailureCategory
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=5)
    recommended_action: RecommendedAction
    repair_hint: str = Field(
        default="", max_length=500, description="What a test change would look like, if any."
    )


class StepChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["replace", "insert_after", "remove"]
    step_index: int = Field(ge=0, le=99, description="0-based index in the CURRENT plan.")
    step: Step | None = Field(default=None, description="The new step for replace/insert_after.")
    reason: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def _needs_step(self) -> StepChange:
        if self.op in ("replace", "insert_after") and self.step is None:
            raise ValueError(f"'{self.op}' needs a step.")
        if self.op == "remove" and self.step is not None:
            raise ValueError("'remove' does not take a step.")
        return self


class RepairOutput(BaseModel):
    """A minimal plan edit, or no edit when the application (not the test) is at fault."""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["fix_test", "no_test_change"]
    rationale: str = Field(min_length=1, max_length=800)
    changes: list[StepChange] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _consistent(self) -> RepairOutput:
        if self.verdict == "fix_test" and not self.changes:
            raise ValueError("A test fix needs at least one change.")
        if self.verdict == "no_test_change":
            self.changes = []
        indices = [c.step_index for c in self.changes if c.op != "insert_after"]
        if len(indices) != len(set(indices)):
            raise ValueError("Each step may be replaced or removed at most once.")
        return self
