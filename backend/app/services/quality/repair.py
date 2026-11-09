"""Applying AI repair edits to a plan and describing them as a step-level diff."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.domain.failure import StepChange
from app.domain.test_plan import Step, TestPlan


class RepairNotApplicableError(ValueError):
    pass


def build_diff(plan: TestPlan, changes: list[StepChange]) -> list[dict[str, Any]]:
    """Rows in the order of the new plan, each ``same``, ``changed``, ``added`` or ``removed``."""
    count = len(plan.steps)
    for edit in changes:
        if edit.step_index >= count:
            raise RepairNotApplicableError(
                f"Change refers to step index {edit.step_index}, but the plan has {count} steps."
            )
    replaced = {c.step_index: c for c in changes if c.op in ("replace", "remove")}
    inserted: dict[int, list[StepChange]] = defaultdict(list)
    for edit in changes:
        if edit.op == "insert_after":
            inserted[edit.step_index].append(edit)

    def dump(step: Step | None) -> dict[str, Any] | None:
        return step.model_dump(mode="json", exclude_none=True) if step is not None else None

    rows: list[dict[str, Any]] = []
    for index, step in enumerate(plan.steps):
        change = replaced.get(index)
        if change is None:
            rows.append({"kind": "same", "index": index, "before": dump(step), "after": dump(step)})
        elif change.op == "replace":
            rows.append(
                {
                    "kind": "changed",
                    "index": index,
                    "before": dump(step),
                    "after": dump(change.step),
                    "reason": change.reason,
                }
            )
        else:
            rows.append(
                {
                    "kind": "removed",
                    "index": index,
                    "before": dump(step),
                    "after": None,
                    "reason": change.reason,
                }
            )
        for insert in inserted[index]:
            rows.append(
                {
                    "kind": "added",
                    "index": None,
                    "before": None,
                    "after": dump(insert.step),
                    "reason": insert.reason,
                }
            )
    return rows


def apply_diff(plan: TestPlan, diff: list[dict[str, Any]]) -> TestPlan:
    steps = [row["after"] for row in diff if row["after"] is not None]
    if not steps:
        raise RepairNotApplicableError("The change would remove every step.")
    return TestPlan.model_validate({**plan.model_dump(mode="json"), "steps": steps})
