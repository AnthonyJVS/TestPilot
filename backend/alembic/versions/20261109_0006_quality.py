"""quality: failure analyses, repair proposals, page snapshots of failed steps

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-09 18:47:13.635022
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "failure_analyses",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("test_case_id", sa.Uuid(), nullable=True),
        sa.Column("test_version_id", sa.Uuid(), nullable=True),
        sa.Column("failed_step_index", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("evidence", JSON, nullable=False),
        sa.Column("used_screenshot", sa.Boolean(), nullable=False),
        sa.Column("result", JSON, nullable=True),
        sa.Column("ai_request_ids", JSON, nullable=False),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["workflow_executions.id"],
            name=op.f("fk_failure_analyses_execution_id_workflow_executions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_failure_analyses_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["test_case_id"],
            ["test_cases.id"],
            name=op.f("fk_failure_analyses_test_case_id_test_cases"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["test_version_id"],
            ["test_versions.id"],
            name=op.f("fk_failure_analyses_test_version_id_test_versions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_failure_analyses")),
    )
    with op.batch_alter_table("failure_analyses", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_failure_analyses_execution_id"), ["execution_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_failure_analyses_owner_id"), ["owner_id"], unique=False
        )

    op.create_table(
        "repair_proposals",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("test_case_id", sa.Uuid(), nullable=False),
        sa.Column("base_version_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("verdict", sa.String(length=20), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("changes", JSON, nullable=False),
        sa.Column("diff", JSON, nullable=False),
        sa.Column("proposed_plan", JSON, nullable=True),
        sa.Column("issues", JSON, nullable=False),
        sa.Column("ai_request_ids", JSON, nullable=False),
        sa.Column("resulting_version_id", sa.Uuid(), nullable=True),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", TS, nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["failure_analyses.id"],
            name=op.f("fk_repair_proposals_analysis_id_failure_analyses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["base_version_id"],
            ["test_versions.id"],
            name=op.f("fk_repair_proposals_base_version_id_test_versions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"],
            ["users.id"],
            name=op.f("fk_repair_proposals_decided_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_repair_proposals_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resulting_version_id"],
            ["test_versions.id"],
            name=op.f("fk_repair_proposals_resulting_version_id_test_versions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["test_case_id"],
            ["test_cases.id"],
            name=op.f("fk_repair_proposals_test_case_id_test_cases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_repair_proposals")),
    )
    with op.batch_alter_table("repair_proposals", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_repair_proposals_analysis_id"), ["analysis_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_repair_proposals_owner_id"), ["owner_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_repair_proposals_test_case_id"), ["test_case_id"], unique=False
        )

    with op.batch_alter_table("execution_steps", schema=None) as batch_op:
        batch_op.add_column(sa.Column("page_snapshot", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("execution_steps", schema=None) as batch_op:
        batch_op.drop_column("page_snapshot")

    with op.batch_alter_table("repair_proposals", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_repair_proposals_test_case_id"))
        batch_op.drop_index(batch_op.f("ix_repair_proposals_owner_id"))
        batch_op.drop_index(batch_op.f("ix_repair_proposals_analysis_id"))

    op.drop_table("repair_proposals")
    with op.batch_alter_table("failure_analyses", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_failure_analyses_owner_id"))
        batch_op.drop_index(batch_op.f("ix_failure_analyses_execution_id"))

    op.drop_table("failure_analyses")
