"""Static workflow validation (docs/WORKFLOW_ENGINE.md §3). Errors block runs; warnings don't."""

from __future__ import annotations

from collections import defaultdict, deque

from pydantic import BaseModel, ValidationError

from app.domain.workflow import GraphIssue, GraphNode, WorkflowGraph
from app.services.workflows.registry import NodeRegistry, NodeType, ValidationContext, compatible


def topological_order(graph: WorkflowGraph) -> list[str] | None:
    """Kahn's algorithm with node ID as tie-breaker (deterministic). None if there is a cycle."""
    indegree = {n.id: 0 for n in graph.nodes}
    children: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        if edge.source in indegree and edge.target in indegree:
            indegree[edge.target] += 1
            children[edge.source].append(edge.target)
    ready = deque(sorted(n for n, d in indegree.items() if d == 0))
    order: list[str] = []
    while ready:
        current = ready.popleft()
        order.append(current)
        for child in sorted(children[current]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    return order if len(order) == len(indegree) else None


def parse_config(node_type: NodeType, node: GraphNode) -> tuple[BaseModel | None, list[GraphIssue]]:
    try:
        return node_type.config_model.model_validate(node.config), []
    except ValidationError as exc:
        issues = []
        for error in exc.errors()[:5]:
            where = ".".join(str(p) for p in error["loc"]) or "config"
            message = str(error["msg"]).removeprefix("Value error, ")
            issues.append(
                GraphIssue(
                    severity="error",
                    code="node.invalid_config",
                    message=f"{where}: {message}",
                    node_id=node.id,
                )
            )
        return None, issues


def validate_graph(
    graph: WorkflowGraph, registry: NodeRegistry, ctx: ValidationContext
) -> list[GraphIssue]:
    issues: list[GraphIssue] = []
    if not graph.nodes:
        return [GraphIssue(severity="error", code="graph.empty", message="Add at least one node.")]

    types: dict[str, NodeType] = {}
    for node in graph.nodes:
        node_type = registry.get(node.type)
        if node_type is None:
            issues.append(
                GraphIssue(
                    severity="error",
                    code="node.unknown_type",
                    message=f"Unknown node type '{node.type}'.",
                    node_id=node.id,
                )
            )
            continue
        types[node.id] = node_type
        if not node_type.available:
            issues.append(
                GraphIssue(
                    severity="error",
                    code="node.unavailable",
                    message=f"{node_type.label} is planned for milestone {node_type.milestone}.",
                    node_id=node.id,
                )
            )
            continue
        config, config_issues = parse_config(node_type, node)
        issues.extend(config_issues)
        if config is not None:
            issues.extend(node_type.validate_static(node, config, ctx))

    connected: dict[tuple[str, str], int] = defaultdict(int)
    touched: set[str] = set()
    for edge in graph.edges:
        source_type, target_type = types.get(edge.source), types.get(edge.target)
        if graph.node(edge.source) is None or graph.node(edge.target) is None:
            issues.append(
                GraphIssue(
                    severity="error",
                    code="edge.dangling",
                    message="The connection points to a missing node.",
                    edge_id=edge.id,
                )
            )
            continue
        touched.update((edge.source, edge.target))
        if edge.source == edge.target:
            issues.append(
                GraphIssue(
                    severity="error",
                    code="edge.self_loop",
                    message="A node cannot connect to itself.",
                    edge_id=edge.id,
                )
            )
            continue
        if source_type is None or target_type is None:
            continue
        out_port = source_type.output(edge.source_handle)
        in_port = target_type.input(edge.target_handle)
        if out_port is None or in_port is None:
            issues.append(
                GraphIssue(
                    severity="error",
                    code="edge.unknown_port",
                    message="The connection uses a port that does not exist.",
                    edge_id=edge.id,
                )
            )
            continue
        if not compatible(out_port.type, in_port.type):
            issues.append(
                GraphIssue(
                    severity="error",
                    code="edge.incompatible",
                    message=(
                        f"{source_type.label} '{out_port.label}' ({out_port.type}) cannot feed "
                        f"{target_type.label} '{in_port.label}' ({in_port.type})."
                    ),
                    edge_id=edge.id,
                )
            )
        connected[(edge.target, edge.target_handle)] += 1
        if connected[(edge.target, edge.target_handle)] > 1 and not in_port.multi:
            issues.append(
                GraphIssue(
                    severity="error",
                    code="edge.duplicate_input",
                    message=f"'{in_port.label}' accepts one connection.",
                    edge_id=edge.id,
                )
            )

    for node in graph.nodes:
        node_type = types.get(node.id)
        if node_type is None:
            continue
        for port in node_type.inputs:
            if port.required and not connected[(node.id, port.name)]:
                issues.append(
                    GraphIssue(
                        severity="error",
                        code="node.input_missing",
                        message=f"Connect '{port.label}' ({port.type}).",
                        node_id=node.id,
                    )
                )
        if len(graph.nodes) > 1 and node.id not in touched:
            issues.append(
                GraphIssue(
                    severity="warning",
                    code="node.unconnected",
                    message="This node is not connected to anything.",
                    node_id=node.id,
                )
            )

    if topological_order(graph) is None:
        issues.append(
            GraphIssue(
                severity="error",
                code="graph.cycle",
                message="The workflow contains a loop. Use a node's retry policy instead.",
            )
        )
    return issues


def has_errors(issues: list[GraphIssue]) -> bool:
    return any(issue.severity == "error" for issue in issues)
