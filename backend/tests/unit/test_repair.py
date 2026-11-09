"""Repair edits: diff building, application and the AI output contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.failure import FailureAnalysisOutput, RepairOutput, StepChange
from app.domain.test_plan import Step, TestPlan
from app.services.quality.repair import RepairNotApplicableError, apply_diff, build_diff


def plan() -> TestPlan:
    return TestPlan.model_validate(
        {
            "name": "Login",
            "steps": [
                {"action": "goto", "description": "Open", "value": "/"},
                {
                    "action": "click",
                    "description": "Log in",
                    "locator": {"strategy": "role", "role": "button", "value": "Log in"},
                },
                {"action": "expect_title", "description": "Title", "value": "Home"},
            ],
        }
    )


def click(name: str) -> Step:
    return Step.model_validate(
        {
            "action": "click",
            "description": name,
            "locator": {"strategy": "role", "role": "button", "value": name},
        }
    )


def test_diff_and_apply_replace_insert_remove() -> None:
    changes = [
        StepChange(op="replace", step_index=1, step=click("Sign in"), reason="renamed"),
        StepChange(op="insert_after", step_index=1, step=click("Accept"), reason="new banner"),
        StepChange(op="remove", step_index=2, reason="obsolete"),
    ]
    diff = build_diff(plan(), changes)
    assert [row["kind"] for row in diff] == ["same", "changed", "added", "removed"]
    fixed = apply_diff(plan(), diff)
    assert [s.description for s in fixed.steps] == ["Open", "Sign in", "Accept"]


def test_out_of_range_and_empty_results_are_refused() -> None:
    with pytest.raises(RepairNotApplicableError):
        build_diff(plan(), [StepChange(op="remove", step_index=7, reason="x")])
    removals = [StepChange(op="remove", step_index=i, reason="x") for i in range(3)]
    with pytest.raises(RepairNotApplicableError):
        apply_diff(plan(), build_diff(plan(), removals))


def test_output_contracts() -> None:
    with pytest.raises(ValidationError, match="needs at least one change"):
        RepairOutput(verdict="fix_test", rationale="x", changes=[])
    with pytest.raises(ValidationError, match="at most once"):
        RepairOutput(
            verdict="fix_test",
            rationale="x",
            changes=[
                StepChange(op="remove", step_index=1, reason="a"),
                StepChange(op="replace", step_index=1, step=click("B"), reason="b"),
            ],
        )
    with pytest.raises(ValidationError, match="needs a step"):
        StepChange(op="replace", step_index=0, reason="x")
    # A "no change" verdict never carries edits, whatever the model sent.
    quiet = RepairOutput(
        verdict="no_test_change",
        rationale="bug",
        changes=[StepChange(op="remove", step_index=0, reason="x")],
    )
    assert quiet.changes == []
    analysis = FailureAnalysisOutput.model_validate(
        {
            "summary": "s",
            "category": "timing",
            "hypotheses": [
                {"statement": "h", "confidence": "low", "evidence_ids": ["E1", "bad", "E12"]}
            ],
            "recommended_action": "retry",
        }
    )
    assert analysis.hypotheses[0].evidence_ids == ["E1", "E12"]
