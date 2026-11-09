"""Failure analyses and human-approved repair proposals (milestone 7)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, JSONType, UUIDPrimaryKeyMixin, utcnow


class FailureAnalysis(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "failure_analyses"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("test_cases.id", ondelete="SET NULL"), nullable=True
    )
    test_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("test_versions.id", ondelete="SET NULL"), nullable=True
    )
    failed_step_index: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # completed | failed
    # Verified facts collected from the run: [{"id": "E1", "kind", "title", "detail"}]
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, nullable=False)
    used_screenshot: Mapped[bool] = mapped_column(default=False, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    ai_request_ids: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)


class RepairProposal(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "repair_proposals"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("failure_analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    base_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("test_versions.id", ondelete="SET NULL"), nullable=True
    )
    # proposed | no_change | invalid | approved | rejected | superseded
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, nullable=False)
    diff: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, nullable=False)
    proposed_plan: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list, nullable=False)
    ai_request_ids: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    resulting_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("test_versions.id", ondelete="SET NULL"), nullable=True
    )
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
