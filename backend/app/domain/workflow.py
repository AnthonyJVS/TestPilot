"""Workflow graphs (Workflow Studio, milestone 5).

A workflow version stores one immutable graph document: typed nodes (each with a validated
config, an optional retry policy and timeout) and edges from an output handle to an input
handle. The graph is data; the engine interprets it. No node runs user-supplied code.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NODE_ID = r"^[A-Za-z0-9_-]{1,40}$"
HANDLE = r"^[a-z][a-z0-9_]{0,30}$"


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = 0
    y: float = 0


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=1, ge=1, le=5)
    backoff: Literal["fixed", "exponential"] = "exponential"
    base_seconds: float = Field(default=1.0, ge=0, le=60)
    max_seconds: float = Field(default=30.0, ge=0, le=300)
    retry_on: Literal["transient", "any"] = "transient"

    def delay(self, attempt: int) -> float:
        """Seconds to wait before attempt ``attempt + 1`` (``attempt`` starts at 1)."""
        if self.backoff == "fixed":
            return min(self.base_seconds, self.max_seconds)
        return float(min(self.base_seconds * 2 ** (attempt - 1), self.max_seconds))


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=NODE_ID)
    type: str = Field(min_length=1, max_length=60)
    label: str = Field(default="", max_length=80)
    position: Position = Position()
    config: dict[str, Any] = Field(default_factory=dict)
    retry: RetryPolicy = RetryPolicy()
    timeout_seconds: int | None = Field(default=None, ge=1, le=900)


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=NODE_ID)
    source: str = Field(pattern=NODE_ID)
    source_handle: str = Field(pattern=HANDLE)
    target: str = Field(pattern=NODE_ID)
    target_handle: str = Field(pattern=HANDLE)


class WorkflowGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[GraphNode] = Field(default_factory=list, max_length=100)
    edges: list[GraphEdge] = Field(default_factory=list, max_length=300)

    @model_validator(mode="after")
    def _unique(self) -> WorkflowGraph:
        node_ids = [n.id for n in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Node IDs must be unique.")
        edge_ids = [e.id for e in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("Edge IDs must be unique.")
        return self

    def node(self, node_id: str) -> GraphNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)


class GraphIssue(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None
