"""Starter graphs offered when a workflow is created."""

from __future__ import annotations

import uuid
from typing import Any

from app.domain.workflow import WorkflowGraph


def _node(
    node_id: str, type_: str, label: str, x: float, y: float, **config: Any
) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": type_,
        "label": label,
        "position": {"x": x, "y": y},
        "config": config,
    }


def _edge(source: str, source_handle: str, target: str, target_handle: str) -> dict[str, Any]:
    return {
        "id": f"{source}-{source_handle}-{target}-{target_handle}"[:40],
        "source": source,
        "source_handle": source_handle,
        "target": target,
        "target_handle": target_handle,
    }


def build(template: str, *, test_case_id: uuid.UUID | None = None) -> WorkflowGraph:
    if template == "run_test":
        nodes = [
            _node("launch", "browser.launch", "Launch Chromium", 0, 120),
            _node(
                "test",
                "test.run_version",
                "Run test",
                300,
                120,
                test_case_id=str(test_case_id) if test_case_id else None,
            ),
            _node("console", "browser.inspect_console", "Inspect console", 600, 40),
            _node("result", "data.output", "Result", 900, 40),
            _node("failure", "data.output", "Failure", 600, 260),
        ]
        edges = [
            _edge("launch", "session", "test", "session"),
            _edge("test", "session", "console", "session"),
            _edge("console", "report", "result", "value"),
            _edge("test", "error", "failure", "value"),
        ]
    elif template == "generate_and_run":
        nodes = [
            _node(
                "scenario",
                "data.input",
                "Scenario",
                0,
                40,
                text="Open the start page and check that the main heading is visible.",
            ),
            _node("analyze", "ai.requirement_analyzer", "Analyze requirements", 300, 0),
            _node("plan", "ai.test_planner", "Plan the test", 600, 40),
            _node("launch", "browser.launch", "Launch Chromium", 600, 240),
            _node("run", "test.run_plan", "Run the plan", 900, 140),
            _node("result", "data.output", "Result", 1200, 140),
        ]
        edges = [
            _edge("scenario", "text", "analyze", "scenario"),
            _edge("scenario", "text", "plan", "scenario"),
            _edge("analyze", "analysis", "plan", "analysis"),
            _edge("plan", "plan", "run", "plan"),
            _edge("launch", "session", "run", "session"),
            _edge("run", "result", "result", "value"),
        ]
    else:
        nodes, edges = [], []
    return WorkflowGraph.model_validate({"nodes": nodes, "edges": edges})
