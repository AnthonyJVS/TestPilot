"""workflows: versions with graph documents, node executions, artifact node ids

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-09 02:59:38.122009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_workflows_owner_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_workflows_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflows")),
        sa.UniqueConstraint("project_id", "name", name="uq_workflows_project_id_name"),
    )
    with op.batch_alter_table("workflows", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_workflows_owner_id"), ["owner_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_workflows_project_id"), ["project_id"], unique=False)

    op.create_table(
        "workflow_versions",
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("graph", JSON, nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_workflow_versions_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name=op.f("fk_workflow_versions_workflow_id_workflows"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_versions")),
        sa.UniqueConstraint(
            "workflow_id", "version", name="uq_workflow_versions_workflow_id_version"
        ),
    )
    with op.batch_alter_table("workflow_versions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_workflow_versions_workflow_id"), ["workflow_id"], unique=False
        )

    op.create_table(
        "workflow_node_executions",
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(length=60), nullable=False),
        sa.Column("node_type", sa.String(length=60), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("started_at", TS, nullable=True),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("summary", sa.String(length=300), nullable=True),
        sa.Column("output", JSON, nullable=True),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["workflow_executions.id"],
            name=op.f("fk_workflow_node_executions_execution_id_workflow_executions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_node_executions")),
        sa.UniqueConstraint(
            "execution_id", "node_id", name="uq_workflow_node_executions_execution_id_node_id"
        ),
    )
    with op.batch_alter_table("workflow_node_executions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_workflow_node_executions_execution_id"), ["execution_id"], unique=False
        )

    with op.batch_alter_table("execution_artifacts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("node_id", sa.String(length=60), nullable=True))

    with op.batch_alter_table("workflow_executions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("workflow_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("workflow_version_id", sa.Uuid(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_workflow_executions_workflow_id"), ["workflow_id"], unique=False
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_workflow_executions_workflow_version_id_workflow_versions"),
            "workflow_versions",
            ["workflow_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_workflow_executions_workflow_id_workflows"),
            "workflows",
            ["workflow_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("workflow_executions", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_workflow_executions_workflow_id_workflows"), type_="foreignkey"
        )
        batch_op.drop_constraint(
            batch_op.f("fk_workflow_executions_workflow_version_id_workflow_versions"),
            type_="foreignkey",
        )
        batch_op.drop_index(batch_op.f("ix_workflow_executions_workflow_id"))
        batch_op.drop_column("workflow_version_id")
        batch_op.drop_column("workflow_id")

    with op.batch_alter_table("execution_artifacts", schema=None) as batch_op:
        batch_op.drop_column("node_id")

    with op.batch_alter_table("workflow_node_executions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workflow_node_executions_execution_id"))

    op.drop_table("workflow_node_executions")
    with op.batch_alter_table("workflow_versions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workflow_versions_workflow_id"))

    op.drop_table("workflow_versions")
    with op.batch_alter_table("workflows", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workflows_project_id"))
        batch_op.drop_index(batch_op.f("ix_workflows_owner_id"))

    op.drop_table("workflows")
