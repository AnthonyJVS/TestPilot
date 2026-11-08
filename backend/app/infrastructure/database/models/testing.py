"""Projects, environments, test data, suites, test cases, plans and immutable test versions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import (
    Base,
    JSONType,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    utcnow,
)


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_projects_owner_id_name"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    allowed_domains: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)

    environments: Mapped[list[ProjectEnvironment]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ProjectEnvironment.created_at",
    )
    suites: Mapped[list[TestSuite]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TestSuite.created_at",
    )


class ProjectEnvironment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "project_environments"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_project_environments_project_id_name"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="environments")
    variables: Mapped[list[EnvironmentVariable]] = relationship(
        back_populates="environment",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="EnvironmentVariable.name",
    )


class EnvironmentVariable(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Test data. Secret values are encrypted and never returned by the API."""

    __tablename__ = "environment_variables"
    __table_args__ = (
        UniqueConstraint(
            "environment_id", "name", name="uq_environment_variables_environment_id_name"
        ),
    )

    environment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_environments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    is_secret: Mapped[bool] = mapped_column(Boolean, nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)  # plain variables only
    ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    nonce: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    key_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    environment: Mapped[ProjectEnvironment] = relationship(back_populates="variables")


class TestSuite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "test_suites"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_test_suites_project_id_name"),
    )
    __test__ = False  # not a pytest test class

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    project: Mapped[Project] = relationship(back_populates="suites")
    cases: Mapped[list[TestCase]] = relationship(
        back_populates="suite",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TestCase.created_at",
    )


class TestCase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "test_cases"
    __test__ = False

    suite_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_suites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    scenario: Mapped[str] = mapped_column(Text, default="", nullable=False)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "test_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_test_cases_current_version_id_test_versions",
        ),
        nullable=True,
    )

    suite: Mapped[TestSuite] = relationship(back_populates="cases")
    plans: Mapped[list[TestPlanRecord]] = relationship(
        back_populates="test_case",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TestPlanRecord.revision",
    )
    versions: Mapped[list[TestVersion]] = relationship(
        back_populates="test_case",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="TestVersion.test_case_id",
        order_by="TestVersion.version",
    )


class TestPlanRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A draft or approved structured plan for a test case (table ``test_plans``)."""

    __tablename__ = "test_plans"
    __table_args__ = (
        UniqueConstraint("test_case_id", "revision", name="uq_test_plans_test_case_id_revision"),
    )
    __test__ = False

    test_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # ai | manual | edited
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # draft | approved
    plan: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    ai_request_ids: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    scenario_snapshot: Mapped[str] = mapped_column(Text, default="", nullable=False)

    test_case: Mapped[TestCase] = relationship(back_populates="plans")


class TestVersion(UUIDPrimaryKeyMixin, Base):
    """Immutable, approved, executable version of a test (plan snapshot + rendered code)."""

    __tablename__ = "test_versions"
    __table_args__ = (
        UniqueConstraint("test_case_id", "version", name="uq_test_versions_test_case_id_version"),
    )
    __test__ = False

    test_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("test_plans.id", ondelete="SET NULL"), nullable=True
    )
    plan: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    code_python: Mapped[str] = mapped_column(Text, nullable=False)
    code_typescript: Mapped[str] = mapped_column(Text, nullable=False)
    renderer_version: Mapped[str] = mapped_column(String(20), nullable=False)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)

    test_case: Mapped[TestCase] = relationship(
        back_populates="versions", foreign_keys=[test_case_id]
    )
