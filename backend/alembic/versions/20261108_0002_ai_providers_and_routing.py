"""ai providers, credentials, model catalog, routing and request log

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "ai_providers",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("provider_type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("config", JSON, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_validated_at", TS, nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.current_timestamp(), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_ai_providers_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_providers")),
        sa.UniqueConstraint("owner_id", "name", name="uq_ai_providers_owner_id_name"),
    )
    op.create_index(op.f("ix_ai_providers_owner_id"), "ai_providers", ["owner_id"], unique=False)

    op.create_table(
        "ai_credentials",
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("key_id", sa.String(length=32), nullable=False),
        sa.Column("key_hint", sa.String(length=8), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("rotated_at", TS, nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["ai_providers.id"],
            name=op.f("fk_ai_credentials_provider_id_ai_providers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_credentials")),
        sa.UniqueConstraint("provider_id", name=op.f("uq_ai_credentials_provider_id")),
    )
    op.create_table(
        "ai_model_configurations",
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("capabilities", JSON, nullable=False),
        sa.Column("input_token_limit", sa.Integer(), nullable=True),
        sa.Column("output_token_limit", sa.Integer(), nullable=True),
        sa.Column("listed_by_provider", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.current_timestamp(), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["ai_providers.id"],
            name=op.f("fk_ai_model_configurations_provider_id_ai_providers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_model_configurations")),
        sa.UniqueConstraint(
            "provider_id", "model_id", name="uq_ai_model_configurations_provider_id_model_id"
        ),
    )
    op.create_index(
        op.f("ix_ai_model_configurations_provider_id"),
        "ai_model_configurations",
        ["provider_id"],
        unique=False,
    )

    op.create_table(
        "ai_requests",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("task", sa.String(length=40), nullable=True),
        sa.Column("origin", sa.String(length=40), nullable=False),
        sa.Column("route_source", sa.String(length=30), nullable=True),
        sa.Column("requested_provider_id", sa.Uuid(), nullable=True),
        sa.Column("requested_provider_type", sa.String(length=32), nullable=False),
        sa.Column("requested_model", sa.String(length=200), nullable=False),
        sa.Column("actual_provider_id", sa.Uuid(), nullable=True),
        sa.Column("actual_provider_type", sa.String(length=32), nullable=True),
        sa.Column("actual_model", sa.String(length=200), nullable=True),
        sa.Column("provider_request_id", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("fallback_reason", sa.String(length=300), nullable=True),
        sa.Column("retry_history", JSON, nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("request_preview", JSON, nullable=True),
        sa.Column("response_preview", JSON, nullable=True),
        sa.Column("started_at", TS, nullable=False),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actual_provider_id"],
            ["ai_providers.id"],
            name=op.f("fk_ai_requests_actual_provider_id_ai_providers"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_ai_requests_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_provider_id"],
            ["ai_providers.id"],
            name=op.f("fk_ai_requests_requested_provider_id_ai_providers"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_requests")),
    )
    op.create_index(
        "ix_ai_requests_owner_id_started_at",
        "ai_requests",
        ["owner_id", "started_at"],
        unique=False,
    )

    op.create_table(
        "ai_routing_settings",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("default_model_id", sa.Uuid(), nullable=True),
        sa.Column("fallback_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("fallback_model_id", sa.Uuid(), nullable=True),
        sa.Column("daily_request_limit", sa.Integer(), nullable=True),
        sa.Column("store_payload_previews", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.current_timestamp(), nullable=False),
        sa.ForeignKeyConstraint(
            ["default_model_id"],
            ["ai_model_configurations.id"],
            name=op.f("fk_ai_routing_settings_default_model_id_ai_model_configurations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["fallback_model_id"],
            ["ai_model_configurations.id"],
            name=op.f("fk_ai_routing_settings_fallback_model_id_ai_model_configurations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_ai_routing_settings_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_routing_settings")),
        sa.UniqueConstraint("owner_id", name=op.f("uq_ai_routing_settings_owner_id")),
    )
    op.create_table(
        "ai_task_routing",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("task", sa.String(length=40), nullable=False),
        sa.Column("model_configuration_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.current_timestamp(), nullable=False),
        sa.ForeignKeyConstraint(
            ["model_configuration_id"],
            ["ai_model_configurations.id"],
            name=op.f("fk_ai_task_routing_model_configuration_id_ai_model_configurations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_ai_task_routing_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_task_routing")),
        sa.UniqueConstraint("owner_id", "task", name="uq_ai_task_routing_owner_id_task"),
    )


def downgrade() -> None:
    op.drop_table("ai_task_routing")
    op.drop_table("ai_routing_settings")
    op.drop_index("ix_ai_requests_owner_id_started_at", table_name="ai_requests")
    op.drop_table("ai_requests")
    op.drop_index(
        op.f("ix_ai_model_configurations_provider_id"), table_name="ai_model_configurations"
    )
    op.drop_table("ai_model_configurations")
    op.drop_table("ai_credentials")
    op.drop_index(op.f("ix_ai_providers_owner_id"), table_name="ai_providers")
    op.drop_table("ai_providers")
