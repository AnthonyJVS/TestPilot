"""Workflows (Workflow Studio) and per-node execution records.

The graph of a version is one immutable, validated JSON document (ADR-019): nodes and edges are
always read and written together, so separate node/edge tables would add joins without
enabling any query the product needs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import (
    Base,
    JSONType,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    utcnow,
)


class Workflow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workflows"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_workflows_project_id_name"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    versions: Mapped[list[WorkflowVersion]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="WorkflowVersion.version",
    )


class WorkflowVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (
        UniqueConstraint("workflow_id", "version", name="uq_workflow_versions_workflow_id_version"),
    )

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    graph: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)

    workflow: Mapped[Workflow] = relationship(back_populates="versions")


class NodeExecution(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "workflow_node_executions"
    __table_args__ = (
        UniqueConstraint(
            "execution_id", "node_id", name="uq_workflow_node_executions_execution_id_node_id"
        ),
    )

    execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(String(60), nullable=False)
    node_type: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str | None] = mapped_column(String(300), nullable=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
