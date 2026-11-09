"""Verified evidence for failure analysis, collected by TestPilot (not by the AI).

Each item gets an ID (E1, E2, ...) that the AI must cite. Everything here comes from the run's
persisted records, which were already scrubbed of secret values.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.domain.test_plan import Step, TestPlan
from app.infrastructure.database.models import ExecutionEvent, ExecutionStep, TestExecution

MAX_SNAPSHOT_CHARS = 6_000
MAX_LIST = 10


def _number(items: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{"id": f"E{i}", **item} for i, item in enumerate(items, start=1)]


def describe_step(step: Step) -> str:
    data: dict[str, Any] = {"action": step.action}
    if step.locator is not None:
        data["locator"] = step.locator.model_dump(exclude_none=True, exclude_defaults=True) | {
            "strategy": step.locator.strategy,
            "value": step.locator.value,
        }
    for key in ("value", "match", "state", "timeout_ms"):
        if getattr(step, key) is not None:
            data[key] = getattr(step, key)
    return json.dumps(data, ensure_ascii=False)


def _page_events(
    events: list[ExecutionEvent], *, node_id: str | None, step_index: int | None
) -> tuple[list[str], list[str], list[str]]:
    console, network, blocked = [], [], []
    for event in events:
        if node_id is not None and event.node_id != node_id:
            continue
        if (
            step_index is not None
            and event.step_index is not None
            and event.step_index > step_index
        ):
            continue
        if event.type == "browser.console" and event.level != "info":
            console.append(event.message)
        elif event.type == "browser.network.failed":
            network.append(event.message)
        elif event.type == "browser.request.blocked":
            blocked.append(event.message)
    return console[:MAX_LIST], network[:MAX_LIST], blocked[:MAX_LIST]


def test_run_evidence(
    *,
    test: TestExecution,
    plan: TestPlan | None,
    failed: ExecutionStep | None,
    error_code: str | None,
    error_message: str | None,
    events: list[ExecutionEvent],
    history: list[tuple[str, datetime]],
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if failed is not None:
        definition = (
            describe_step(plan.steps[failed.index])
            if plan is not None and failed.index < len(plan.steps)
            else failed.action
        )
        items.append(
            {
                "kind": "step",
                "title": f"Step {failed.index + 1} failed: {failed.description}",
                "detail": f"Definition: {definition}",
            }
        )
        items.append(
            {
                "kind": "error",
                "title": f"Error {failed.error_code or 'unknown'} after {failed.duration_ms} ms",
                "detail": failed.error_message or "",
            }
        )
        items.append(
            {
                "kind": "page",
                "title": "Page at the failure",
                "detail": f"URL: {failed.url or 'unknown'}",
            }
        )
        if failed.page_snapshot:
            snapshot = failed.page_snapshot[:MAX_SNAPSHOT_CHARS]
            items.append(
                {
                    "kind": "snapshot",
                    "title": "Accessibility tree of the page when the step failed",
                    "detail": snapshot,
                }
            )
        passed = [s for s in test.steps if s.index < failed.index and s.status == "passed"]
        if passed:
            timings = ", ".join(f"{s.index + 1}: {s.duration_ms} ms" for s in passed)
            items.append(
                {
                    "kind": "progress",
                    "title": f"{len(passed)} earlier step(s) passed",
                    "detail": f"Durations — {timings}",
                }
            )
    else:
        items.append(
            {
                "kind": "error",
                "title": f"The run stopped before a step failed ({error_code or 'unknown'})",
                "detail": error_message or "",
            }
        )
    step_index = failed.index if failed else None
    console, network, blocked = _page_events(events, node_id="execute_test", step_index=step_index)
    items.append(
        {
            "kind": "console",
            "title": f"{len(console)} console error(s) or warning(s) up to the failure",
            "detail": "\n".join(console) or "None",
        }
    )
    if network:
        items.append(
            {
                "kind": "network",
                "title": f"{len(network)} failed request(s)",
                "detail": "\n".join(network),
            }
        )
    if blocked:
        items.append(
            {
                "kind": "blocked",
                "title": f"{len(blocked)} request(s) blocked by the network policy",
                "detail": "\n".join(blocked),
            }
        )
    if history:
        passes = sum(1 for status, _ in history if status == "passed")
        last_pass = next((at for status, at in history if status == "passed"), None)
        detail = f"{passes} of the last {len(history)} earlier run(s) of this version passed"
        if last_pass is not None:
            detail += f"; last pass {last_pass.isoformat(timespec='minutes')}"
        items.append(
            {"kind": "history", "title": "Earlier runs of this test version", "detail": detail}
        )
    else:
        items.append(
            {
                "kind": "history",
                "title": "Earlier runs of this test version",
                "detail": "This is the first run.",
            }
        )
    items.append(
        {
            "kind": "environment",
            "title": "Run environment",
            "detail": (
                f"Environment {test.environment_name} at {test.base_url}; "
                f"{test.browser} {test.browser_version or ''}".strip()
            ),
        }
    )
    return _number(items)


def node_evidence(
    *,
    node_label: str,
    error_code: str,
    error_message: str,
    url: str | None,
    snapshot: str | None,
    events: list[ExecutionEvent],
    failed_node_id: str,
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = [
        {"kind": "step", "title": f"Node '{node_label}' failed", "detail": f"Error {error_code}"},
        {"kind": "error", "title": f"Error {error_code}", "detail": error_message},
        {"kind": "page", "title": "Page at the failure", "detail": f"URL: {url or 'unknown'}"},
    ]
    if snapshot:
        items.append(
            {
                "kind": "snapshot",
                "title": "Accessibility tree of the page when the step failed",
                "detail": snapshot[:MAX_SNAPSHOT_CHARS],
            }
        )
    console, network, blocked = _page_events(events, node_id=failed_node_id, step_index=None)
    items.append(
        {
            "kind": "console",
            "title": f"{len(console)} console error(s) or warning(s)",
            "detail": "\n".join(console) or "None",
        }
    )
    if network:
        items.append(
            {
                "kind": "network",
                "title": f"{len(network)} failed request(s)",
                "detail": "\n".join(network),
            }
        )
    if blocked:
        items.append(
            {
                "kind": "blocked",
                "title": f"{len(blocked)} blocked request(s)",
                "detail": "\n".join(blocked),
            }
        )
    return _number(items)
