"""AI provider connections, encrypted credentials, model catalog, routing and the AI request log."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import (
    Base,
    JSONType,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    utcnow,
)


class AIProviderConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A user's connection to one provider account (table ``ai_providers``)."""

    __tablename__ = "ai_providers"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_ai_providers_owner_id_name"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="untested", nullable=False)
    last_validated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    credential: Mapped[AICredential | None] = relationship(
        back_populates="provider", cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )
    models: Mapped[list[AIModelConfiguration]] = relationship(
        back_populates="provider",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AIModelConfiguration.model_id",
    )


class AICredential(UUIDPrimaryKeyMixin, Base):
    """Encrypted API key for a connection. Only a short hint is ever shown again."""

    __tablename__ = "ai_credentials"

    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_id: Mapped[str] = mapped_column(String(32), nullable=False)
    key_hint: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(nullable=True)

    provider: Mapped[AIProviderConnection] = relationship(back_populates="credential")


class AIModelConfiguration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A model available through a connection, discovered from the provider or entered manually."""

    __tablename__ = "ai_model_configurations"
    __table_args__ = (
        UniqueConstraint(
            "provider_id", "model_id", name="uq_ai_model_configurations_provider_id_model_id"
        ),
    )

    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # discovered | manual
    capabilities: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    input_token_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_token_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    listed_by_provider: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )

    provider: Mapped[AIProviderConnection] = relationship(back_populates="models")


class AIRoutingSettings(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-user routing mode, default model, fallback policy, limits and data minimisation."""

    __tablename__ = "ai_routing_settings"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    mode: Mapped[str] = mapped_column(String(20), default="simple", nullable=False)
    default_model_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_model_configurations.id", ondelete="SET NULL"), nullable=True
    )
    fallback_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    fallback_model_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_model_configurations.id", ondelete="SET NULL"), nullable=True
    )
    daily_request_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    store_payload_previews: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )


class AITaskRoute(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Advanced-mode route for one task category (table ``ai_task_routing``)."""

    __tablename__ = "ai_task_routing"
    __table_args__ = (
        UniqueConstraint("owner_id", "task", name="uq_ai_task_routing_owner_id_task"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    task: Mapped[str] = mapped_column(String(40), nullable=False)
    model_configuration_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_model_configurations.id", ondelete="CASCADE"), nullable=False
    )


class AIRequest(UUIDPrimaryKeyMixin, Base):
    """One logical AI operation, including retries and any fallback."""

    __tablename__ = "ai_requests"
    __table_args__ = (Index("ix_ai_requests_owner_id_started_at", "owner_id", "started_at"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    task: Mapped[str | None] = mapped_column(String(40), nullable=True)
    origin: Mapped[str] = mapped_column(String(40), nullable=False)
    route_source: Mapped[str | None] = mapped_column(String(30), nullable=True)

    requested_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="SET NULL"), nullable=True
    )
    requested_provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_model: Mapped[str] = mapped_column(String(200), nullable=False)
    actual_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="SET NULL"), nullable=True
    )
    actual_provider_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actual_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False)  # running|success|error
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fallback_used: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    fallback_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    retry_history: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONType, default=list, nullable=False
    )

    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    request_preview: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    response_preview: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)

    started_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
