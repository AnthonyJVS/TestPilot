"""executions: workflow executions, test executions, steps, events, artifacts

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-09 02:16:25.855111
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "workflow_executions",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("snapshot", JSON, nullable=False),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("cancel_requested_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("started_at", TS, nullable=True),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_workflow_executions_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_workflow_executions_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_executions")),
    )
    with op.batch_alter_table("workflow_executions", schema=None) as batch_op:
        batch_op.create_index(
            "ix_workflow_executions_owner_id_created_at", ["owner_id", "created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_workflow_executions_project_id"), ["project_id"], unique=False
        )
        batch_op.create_index(
            "ix_workflow_executions_status_created_at", ["status", "created_at"], unique=False
        )

    op.create_table(
        "execution_events",
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("ts", TS, nullable=False),
        sa.Column("type", sa.String(length=60), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("level", sa.String(length=10), nullable=False),
        sa.Column("node_id", sa.String(length=60), nullable=True),
        sa.Column("step_index", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", JSON, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["workflow_executions.id"],
            name=op.f("fk_execution_events_execution_id_workflow_executions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_execution_events")),
        sa.UniqueConstraint("execution_id", "seq", name="uq_execution_events_execution_id_seq"),
    )
    op.create_table(
        "test_executions",
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("test_case_id", sa.Uuid(), nullable=True),
        sa.Column("test_version_id", sa.Uuid(), nullable=True),
        sa.Column("environment_id", sa.Uuid(), nullable=True),
        sa.Column("test_name", sa.String(length=200), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("environment_name", sa.String(length=60), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("browser", sa.String(length=20), nullable=False),
        sa.Column("browser_version", sa.String(length=60), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("steps_total", sa.Integer(), nullable=False),
        sa.Column("steps_passed", sa.Integer(), nullable=False),
        sa.Column("steps_failed", sa.Integer(), nullable=False),
        sa.Column("started_at", TS, nullable=True),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["project_environments.id"],
            name=op.f("fk_test_executions_environment_id_project_environments"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["workflow_executions.id"],
            name=op.f("fk_test_executions_execution_id_workflow_executions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["test_case_id"],
            ["test_cases.id"],
            name=op.f("fk_test_executions_test_case_id_test_cases"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["test_version_id"],
            ["test_versions.id"],
            name=op.f("fk_test_executions_test_version_id_test_versions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_executions")),
    )
    with op.batch_alter_table("test_executions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_test_executions_execution_id"), ["execution_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_test_executions_test_case_id"), ["test_case_id"], unique=False
        )

    op.create_table(
        "execution_artifacts",
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("test_execution_id", sa.Uuid(), nullable=True),
        sa.Column("step_index", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.String(length=300), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["workflow_executions.id"],
            name=op.f("fk_execution_artifacts_execution_id_workflow_executions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["test_execution_id"],
            ["test_executions.id"],
            name=op.f("fk_execution_artifacts_test_execution_id_test_executions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_execution_artifacts")),
    )
    with op.batch_alter_table("execution_artifacts", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_execution_artifacts_execution_id"), ["execution_id"], unique=False
        )

    op.create_table(
        "execution_steps",
        sa.Column("test_execution_id", sa.Uuid(), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", TS, nullable=True),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["test_execution_id"],
            ["test_executions.id"],
            name=op.f("fk_execution_steps_test_execution_id_test_executions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_execution_steps")),
        sa.UniqueConstraint(
            "test_execution_id", "index", name="uq_execution_steps_test_execution_id_index"
        ),
    )


def downgrade() -> None:
    op.drop_table("execution_steps")
    with op.batch_alter_table("execution_artifacts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_execution_artifacts_execution_id"))

    op.drop_table("execution_artifacts")
    with op.batch_alter_table("test_executions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_test_executions_test_case_id"))
        batch_op.drop_index(batch_op.f("ix_test_executions_execution_id"))

    op.drop_table("test_executions")
    op.drop_table("execution_events")
    with op.batch_alter_table("workflow_executions", schema=None) as batch_op:
        batch_op.drop_index("ix_workflow_executions_status_created_at")
        batch_op.drop_index(batch_op.f("ix_workflow_executions_project_id"))
        batch_op.drop_index("ix_workflow_executions_owner_id_created_at")

    op.drop_table("workflow_executions")
