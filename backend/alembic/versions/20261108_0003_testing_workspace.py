"""testing workspace: projects, environments, variables, suites, cases, plans, versions

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-08 22:56:43.874917
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("allowed_domains", JSON, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.current_timestamp(), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_projects_owner_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint("owner_id", "name", name="uq_projects_owner_id_name"),
    )
    op.create_index(op.f("ix_projects_owner_id"), "projects", ["owner_id"], unique=False)

    op.create_table(
        "project_environments",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.current_timestamp(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_environments_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_environments")),
        sa.UniqueConstraint("project_id", "name", name="uq_project_environments_project_id_name"),
    )
    op.create_index(
        op.f("ix_project_environments_project_id"),
        "project_environments",
        ["project_id"],
        unique=False,
    )

    op.create_table(
        "test_suites",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.current_timestamp(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_test_suites_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_suites")),
        sa.UniqueConstraint("project_id", "name", name="uq_test_suites_project_id_name"),
    )
    op.create_index(op.f("ix_test_suites_project_id"), "test_suites", ["project_id"], unique=False)

    op.create_table(
        "environment_variables",
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("is_secret", sa.Boolean(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("nonce", sa.LargeBinary(), nullable=True),
        sa.Column("key_id", sa.String(length=32), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.current_timestamp(), nullable=False),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["project_environments.id"],
            name=op.f("fk_environment_variables_environment_id_project_environments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_environment_variables")),
        sa.UniqueConstraint(
            "environment_id", "name", name="uq_environment_variables_environment_id_name"
        ),
    )
    op.create_index(
        op.f("ix_environment_variables_environment_id"),
        "environment_variables",
        ["environment_id"],
        unique=False,
    )

    op.create_table(
        "test_cases",
        sa.Column("suite_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("scenario", sa.Text(), nullable=False),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.current_timestamp(), nullable=False),
        sa.ForeignKeyConstraint(
            ["suite_id"],
            ["test_suites.id"],
            name=op.f("fk_test_cases_suite_id_test_suites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_cases")),
    )
    op.create_index(op.f("ix_test_cases_suite_id"), "test_cases", ["suite_id"], unique=False)

    op.create_table(
        "test_plans",
        sa.Column("test_case_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("plan", JSON, nullable=False),
        sa.Column("analysis", JSON, nullable=True),
        sa.Column("ai_request_ids", JSON, nullable=False),
        sa.Column("scenario_snapshot", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.current_timestamp(), nullable=False),
        sa.ForeignKeyConstraint(
            ["test_case_id"],
            ["test_cases.id"],
            name=op.f("fk_test_plans_test_case_id_test_cases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_plans")),
        sa.UniqueConstraint("test_case_id", "revision", name="uq_test_plans_test_case_id_revision"),
    )
    op.create_index(
        op.f("ix_test_plans_test_case_id"), "test_plans", ["test_case_id"], unique=False
    )

    op.create_table(
        "test_versions",
        sa.Column("test_case_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=True),
        sa.Column("plan", JSON, nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("code_python", sa.Text(), nullable=False),
        sa.Column("code_typescript", sa.Text(), nullable=False),
        sa.Column("renderer_version", sa.String(length=20), nullable=False),
        sa.Column("approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["approved_by_id"],
            ["users.id"],
            name=op.f("fk_test_versions_approved_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["test_plans.id"],
            name=op.f("fk_test_versions_plan_id_test_plans"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["test_case_id"],
            ["test_cases.id"],
            name=op.f("fk_test_versions_test_case_id_test_cases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_versions")),
        sa.UniqueConstraint(
            "test_case_id", "version", name="uq_test_versions_test_case_id_version"
        ),
    )
    op.create_index(
        op.f("ix_test_versions_test_case_id"), "test_versions", ["test_case_id"], unique=False
    )

    # test_cases <-> test_versions reference each other: add the back reference last.
    # Batch mode makes this work on SQLite (table copy) as well as PostgreSQL (ALTER TABLE).
    with op.batch_alter_table("test_cases") as batch_op:
        batch_op.create_foreign_key(
            "fk_test_cases_current_version_id_test_versions",
            "test_versions",
            ["current_version_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("test_cases") as batch_op:
        batch_op.drop_constraint(
            "fk_test_cases_current_version_id_test_versions", type_="foreignkey"
        )
    op.drop_index(op.f("ix_test_versions_test_case_id"), table_name="test_versions")
    op.drop_table("test_versions")
    op.drop_index(op.f("ix_test_plans_test_case_id"), table_name="test_plans")
    op.drop_table("test_plans")
    op.drop_index(op.f("ix_test_cases_suite_id"), table_name="test_cases")
    op.drop_table("test_cases")
    op.drop_index(
        op.f("ix_environment_variables_environment_id"), table_name="environment_variables"
    )
    op.drop_table("environment_variables")
    op.drop_index(op.f("ix_test_suites_project_id"), table_name="test_suites")
    op.drop_table("test_suites")
    op.drop_index(op.f("ix_project_environments_project_id"), table_name="project_environments")
    op.drop_table("project_environments")
    op.drop_index(op.f("ix_projects_owner_id"), table_name="projects")
    op.drop_table("projects")
