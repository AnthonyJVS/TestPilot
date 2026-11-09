"""The node registry used by the API and the engine."""

from __future__ import annotations

from functools import lru_cache

from app.services.workflows.nodes import AVAILABLE, PLANNED
from app.services.workflows.registry import NodeRegistry


@lru_cache
def node_registry() -> NodeRegistry:
    return NodeRegistry([*AVAILABLE, *PLANNED])
