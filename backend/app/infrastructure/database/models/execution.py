"""Executions (ADR-010): every run is a workflow execution with ordered, persisted events.

Milestone 4 creates ``test_run`` executions (built-in template: launch browser → execute test
version → collect artifacts). Milestone 5 adds custom workflow executions to the same tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, JSONType, UUIDPrimaryKeyMixin, utcnow
from app.infrastructure.database.models.workflow import NodeExecution

TERMINAL_STATUSES = frozenset({"passed", "failed", "error", "cancelled"})


class WorkflowExecution(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "workflow_executions"
    __table_args__ = (
        Index("ix_workflow_executions_status_created_at", "status", "created_at"),
        Index("ix_workflow_executions_owner_id_created_at", "owner_id", "created_at"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # test_run (M4) | workflow (M5)
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True, index=True
    )
    workflow_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflow_versions.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    # Resolved configuration the run uses (never secret values). Execution never re-reads
    # editable objects for configuration.
    snapshot: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    test_executions: Mapped[list[TestExecution]] = relationship(
        back_populates="execution", cascade="all, delete-orphan", passive_deletes=True
    )
    node_executions: Mapped[list[NodeExecution]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="NodeExecution.started_at"
    )
    artifacts: Mapped[list[ExecutionArtifact]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ExecutionArtifact.created_at",
    )


class TestExecution(UUIDPrimaryKeyMixin, Base):
    """One test version run inside an execution (names denormalised for history)."""

    __tablename__ = "test_executions"
    __test__ = False

    execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("test_cases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    test_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("test_versions.id", ondelete="SET NULL"), nullable=True
    )
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project_environments.id", ondelete="SET NULL"), nullable=True
    )
    test_name: Mapped[str] = mapped_column(String(200), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    environment_name: Mapped[str] = mapped_column(String(60), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    browser: Mapped[str] = mapped_column(String(20), nullable=False)
    browser_version: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    steps_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    steps_passed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    steps_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    execution: Mapped[WorkflowExecution] = relationship(back_populates="test_executions")
    steps: Mapped[list[ExecutionStep]] = relationship(
        back_populates="test_execution",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ExecutionStep.index",
    )


class ExecutionStep(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "execution_steps"
    __table_args__ = (
        UniqueConstraint(
            "test_execution_id", "index", name="uq_execution_steps_test_execution_id_index"
        ),
    )

    test_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_executions.id", ondelete="CASCADE"), nullable=False
    )
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # pending|running|passed|...
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    test_execution: Mapped[TestExecution] = relationship(back_populates="steps")


class ExecutionEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "execution_events"
    __table_args__ = (
        UniqueConstraint("execution_id", "seq", name="uq_execution_events_execution_id_seq"),
    )

    execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    ts: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    type: Mapped[str] = mapped_column(String(60), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)  # system|node|browser|ai
    level: Mapped[str] = mapped_column(String(10), nullable=False)  # info|warning|error
    node_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    step_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)


class ExecutionArtifact(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "execution_artifacts"

    execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("test_executions.id", ondelete="CASCADE"), nullable=True
    )
    step_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    node_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Relative to ARTIFACTS_DIR; served only through the ownership-checked API.
    storage_path: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)

    execution: Mapped[WorkflowExecution] = relationship(back_populates="artifacts")
