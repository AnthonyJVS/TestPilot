"""Node type contract and registry (docs/WORKFLOW_ENGINE.md §2).

Every node type is a backend class: typed ports, a Pydantic config model (its JSON Schema
drives the Studio inspector), static validation and an async ``execute``. The frontend never
hardcodes node definitions.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from app.domain.workflow import GraphIssue, GraphNode

if TYPE_CHECKING:
    from app.services.workflows.context import RunContext

PortType = Literal["session", "test_plan", "analysis", "result", "json", "text", "any", "error"]
Category = Literal["data", "browser", "test", "ai", "logic"]


@dataclass(frozen=True, slots=True)
class Port:
    name: str
    type: PortType
    label: str
    required: bool = True
    multi: bool = False


ERROR_PORT = Port("error", "error", "On error", required=False)


def compatible(source: PortType, target: PortType) -> bool:
    if source == target or target == "any":
        return True
    if source == "any":
        return target in ("json", "text")
    # Structured payloads can feed generic JSON inputs; errors can be inspected as JSON.
    return target == "json" and source in ("analysis", "result", "test_plan", "error")


class NodeError(Exception):
    """A node failure. ``transient`` errors are retried by the default retry policy."""

    def __init__(self, code: str, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.transient = transient


@dataclass
class NodeResult:
    """Values per output handle. Handles left out are inactive (untaken branches)."""

    outputs: dict[str, Any]
    summary: str = ""


@dataclass
class NodeRun:
    node: GraphNode
    config: BaseModel
    inputs: dict[str, Any]
    ctx: RunContext
    attempt: int = 1
    events: list[str] = field(default_factory=list)


class EmptyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NodeType:
    type_id: ClassVar[str]
    version: ClassVar[int] = 1
    category: ClassVar[Category]
    label: ClassVar[str]
    description: ClassVar[str]
    config_model: ClassVar[type[BaseModel]] = EmptyConfig
    inputs: ClassVar[tuple[Port, ...]] = ()
    outputs: ClassVar[tuple[Port, ...]] = ()
    available: ClassVar[bool] = True
    milestone: ClassVar[int | None] = None
    has_error_output: ClassVar[bool] = True
    entry: ClassVar[bool] = False  # may start a workflow without inputs

    @classmethod
    def all_outputs(cls) -> tuple[Port, ...]:
        return (*cls.outputs, ERROR_PORT) if cls.has_error_output else cls.outputs

    @classmethod
    def input(cls, name: str) -> Port | None:
        return next((p for p in cls.inputs if p.name == name), None)

    @classmethod
    def output(cls, name: str) -> Port | None:
        return next((p for p in cls.all_outputs() if p.name == name), None)

    def validate_static(
        self, node: GraphNode, config: BaseModel, ctx: ValidationContext
    ) -> Iterable[GraphIssue]:
        return ()

    async def execute(self, run: NodeRun) -> NodeResult:  # pragma: no cover - abstract
        raise NotImplementedError


@dataclass
class ValidationContext:
    """What static validation may know about the project (no secret values)."""

    allowed_domains: list[str]
    environments: dict[str, set[str]]  # environment name -> variable names
    secret_names: dict[str, set[str]]  # environment name -> secret variable names
    test_cases: dict[str, tuple[str, int | None]]  # case id -> (name, current version number)


class PlannedNode(NodeType):
    """Shown greyed out in the palette; rejected by the validator."""

    available = False
    has_error_output = False


class NodeRegistry:
    def __init__(self, types: Iterable[type[NodeType]]) -> None:
        self._types: dict[str, NodeType] = {}
        for node_type in types:
            if node_type.type_id in self._types:
                raise ValueError(f"Duplicate node type {node_type.type_id}")
            self._types[node_type.type_id] = node_type()

    def get(self, type_id: str) -> NodeType | None:
        return self._types.get(type_id)

    def all(self) -> list[NodeType]:
        return list(self._types.values())
