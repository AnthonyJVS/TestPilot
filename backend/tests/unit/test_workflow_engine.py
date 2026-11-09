"""Workflow building blocks: conditions, retry backoff, port compatibility, ordering, templates."""

from __future__ import annotations

import uuid

import pytest

from app.domain.workflow import RetryPolicy, WorkflowGraph
from app.services.workflows import templates
from app.services.workflows.catalog import node_registry
from app.services.workflows.nodes import ConditionConfig, evaluate, lookup
from app.services.workflows.registry import ValidationContext, compatible
from app.services.workflows.validation import topological_order, validate_graph


@pytest.mark.parametrize(
    ("path", "operator", "value", "data", "expected"),
    [
        ("status", "equals", "passed", {"status": "passed"}, True),
        ("status", "equals", "PASSED", {"status": "passed"}, True),
        ("status", "not_equals", "passed", {"status": "failed"}, True),
        ("report.errors", "greater_than", "0", {"report": {"errors": 2}}, True),
        ("report.errors", "less_than", "1", {"report": {"errors": 0}}, True),
        ("errors", "greater_than", "x", {"errors": 3}, False),
        ("items", "contains", "b", {"items": ["a", "b"]}, True),
        ("name", "contains", "milk", {"name": "Buy milk"}, True),
        ("missing", "exists", "", {}, False),
        ("missing", "is_empty", "", {}, True),
        ("missing", "not_equals", "x", {}, True),
        ("list.1", "equals", "b", {"list": ["a", "b"]}, True),
        ("", "equals", "hello", "hello", True),
    ],
)
def test_condition_evaluation(
    path: str, operator: str, value: str, data: object, expected: bool
) -> None:
    config = ConditionConfig(path=path, operator=operator, value=value)  # type: ignore[arg-type]
    assert evaluate(config, data) is expected


def test_condition_paths_are_data_only() -> None:
    assert lookup({"a": {"b": 1}}, "a.b") == (True, 1)
    assert lookup({"a": 1}, "a.__class__") == (False, None)
    with pytest.raises(ValueError, match="pattern"):
        ConditionConfig(path="__import__('os')")


def test_retry_backoff() -> None:
    exponential = RetryPolicy(max_attempts=4, base_seconds=1, max_seconds=3)
    assert [exponential.delay(n) for n in (1, 2, 3)] == [1, 2, 3]
    assert RetryPolicy(backoff="fixed", base_seconds=2).delay(3) == 2


def test_port_compatibility() -> None:
    assert compatible("session", "session")
    assert compatible("result", "any") and compatible("analysis", "json")
    assert compatible("error", "json")
    assert not compatible("text", "session")
    assert not compatible("test_plan", "text")


def test_topological_order_is_deterministic_and_detects_cycles() -> None:
    graph = WorkflowGraph.model_validate(
        {
            "nodes": [{"id": i, "type": "logic.delay"} for i in ("c", "a", "b")],
            "edges": [
                {
                    "id": "e1",
                    "source": "a",
                    "source_handle": "value",
                    "target": "c",
                    "target_handle": "value",
                },
                {
                    "id": "e2",
                    "source": "b",
                    "source_handle": "value",
                    "target": "c",
                    "target_handle": "value",
                },
            ],
        }
    )
    assert topological_order(graph) == ["a", "b", "c"]
    graph.edges.append(graph.edges[0].model_copy(update={"id": "e3", "source": "c", "target": "a"}))
    assert topological_order(graph) is None


def test_templates_are_valid_graphs() -> None:
    case_id = uuid.uuid4()
    ctx = ValidationContext(
        allowed_domains=["shop.example.com"],
        environments={"default": set()},
        secret_names={"default": set()},
        test_cases={str(case_id): ("Login", 1)},
    )
    for name in ("run_test", "generate_and_run"):
        graph = templates.build(name, test_case_id=case_id)
        errors = [i for i in validate_graph(graph, node_registry(), ctx) if i.severity == "error"]
        assert errors == [], (name, errors)
    assert templates.build("blank").nodes == []
