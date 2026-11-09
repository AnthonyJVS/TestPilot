"""Use cases for provider connections, credentials and the model catalog."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.crypto import SecretCipher
from app.domain.exceptions import ConflictError, FeatureDisabledError, NotFoundError
from app.infrastructure.database.base import utcnow
from app.infrastructure.database.models import (
    AICredential,
    AIModelConfiguration,
    AIProviderConnection,
)
from app.schemas.ai import ModelCreate, ProviderCreate, ProviderUpdate
from app.services.ai import capabilities as caps
from app.services.ai.client_factory import ProviderClientFactory, credential_aad
from app.services.ai.errors import AIProviderError
from app.services.ai.exceptions import ProviderTypeUnavailableError, UnsafeBaseUrlError
from app.services.ai.registry import ProviderRegistry, ProviderSpec, UnknownProviderTypeError
from app.services.ai.types import ConnectionCheck, ModelInfo, unknown_capabilities
from app.services.ai.url_policy import validate_local_url, validate_public_https_url
from app.services.audit_service import AuditService
from app.services.context import RequestContext


def _key_hint(api_key: str) -> str:
    return api_key[-4:] if len(api_key) >= 12 else "…"


class AIProviderService:
    def __init__(
        self,
        db: AsyncSession,
        registry: ProviderRegistry,
        cipher: SecretCipher,
        clients: ProviderClientFactory,
    ) -> None:
        self._db = db
        self._registry = registry
        self._cipher = cipher
        self._clients = clients
        self._audit = AuditService(db)

    # ----------------------------------------------------------------- queries
    async def list_connections(self, owner_id: uuid.UUID) -> Sequence[AIProviderConnection]:
        result = await self._db.execute(
            select(AIProviderConnection)
            .options(
                selectinload(AIProviderConnection.credential),
                selectinload(AIProviderConnection.models),
            )
            .where(AIProviderConnection.owner_id == owner_id)
            .order_by(AIProviderConnection.created_at)
        )
        return result.scalars().all()

    async def get(self, owner_id: uuid.UUID, provider_id: uuid.UUID) -> AIProviderConnection:
        result = await self._db.execute(
            select(AIProviderConnection)
            .options(
                selectinload(AIProviderConnection.credential),
                selectinload(AIProviderConnection.models),
            )
            .where(
                AIProviderConnection.id == provider_id,
                AIProviderConnection.owner_id == owner_id,
            )
            .execution_options(populate_existing=True)
        )
        connection = result.scalar_one_or_none()
        if connection is None:
            raise NotFoundError("AI provider connection not found.")
        return connection

    async def get_model(
        self, owner_id: uuid.UUID, model_config_id: uuid.UUID
    ) -> AIModelConfiguration:
        result = await self._db.execute(
            select(AIModelConfiguration)
            .join(AIProviderConnection)
            .where(
                AIModelConfiguration.id == model_config_id,
                AIProviderConnection.owner_id == owner_id,
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError("Model not found.")
        return model

    # ---------------------------------------------------------------- mutations
    async def create(
        self, owner_id: uuid.UUID, data: ProviderCreate, ctx: RequestContext
    ) -> AIProviderConnection:
        spec = self._available_spec(data.provider_type)
        api_key = data.api_key.get_secret_value().strip() if data.api_key else None
        if spec.requires_api_key and not api_key:
            raise ConflictError(
                "An API key is required for this provider.", code="ai.api_key_required"
            )
        base_url = await self._checked_base_url(spec, data.base_url)

        connection = AIProviderConnection(
            id=uuid.uuid4(),
            owner_id=owner_id,
            provider_type=spec.type_id,
            name=data.name,
            base_url=base_url,
            config={},
            status="untested",
        )
        self._db.add(connection)
        if api_key:
            self._attach_credential(connection, api_key)
        try:
            await self._db.flush()
        except IntegrityError as exc:
            await self._db.rollback()
            raise ConflictError(
                "You already have a provider connection with this name.",
                code="ai.provider_name_taken",
            ) from exc
        self._audit.record(
            "ai.provider.create",
            "success",
            ctx=ctx,
            user_id=owner_id,
            target_type="ai_provider",
            target_id=str(connection.id),
            details={"provider_type": spec.type_id, "name": data.name},
        )
        await self._db.commit()
        return await self.get(owner_id, connection.id)

    async def update(
        self, owner_id: uuid.UUID, provider_id: uuid.UUID, data: ProviderUpdate, ctx: RequestContext
    ) -> AIProviderConnection:
        connection = await self.get(owner_id, provider_id)
        changed: dict[str, object] = {}
        if data.name is not None and data.name != connection.name:
            connection.name = data.name
            changed["name"] = data.name
        if "base_url" in data.model_fields_set:
            spec = self._registry.get(connection.provider_type)
            connection.base_url = await self._checked_base_url(spec, data.base_url)
            connection.status = "untested"
            changed["base_url"] = connection.base_url
        try:
            await self._db.flush()
        except IntegrityError as exc:
            await self._db.rollback()
            raise ConflictError(
                "You already have a provider connection with this name.",
                code="ai.provider_name_taken",
            ) from exc
        if changed:
            self._audit.record(
                "ai.provider.update",
                "success",
                ctx=ctx,
                user_id=owner_id,
                target_type="ai_provider",
                target_id=str(provider_id),
                details=changed,
            )
        await self._db.commit()
        return await self.get(owner_id, provider_id)

    async def delete(
        self, owner_id: uuid.UUID, provider_id: uuid.UUID, ctx: RequestContext
    ) -> None:
        connection = await self.get(owner_id, provider_id)
        await self._db.delete(connection)
        self._audit.record(
            "ai.provider.delete",
            "success",
            ctx=ctx,
            user_id=owner_id,
            target_type="ai_provider",
            target_id=str(provider_id),
            details={"provider_type": connection.provider_type, "name": connection.name},
        )
        await self._db.commit()

    async def set_credential(
        self, owner_id: uuid.UUID, provider_id: uuid.UUID, api_key: str, ctx: RequestContext
    ) -> AIProviderConnection:
        connection = await self.get(owner_id, provider_id)
        rotated = connection.credential is not None
        if connection.credential is not None:
            await self._db.delete(connection.credential)
            await self._db.flush()
        self._attach_credential(connection, api_key.strip(), rotated=rotated)
        connection.status = "untested"
        connection.last_error = None
        self._audit.record(
            "ai.credential.rotate" if rotated else "ai.credential.set",
            "success",
            ctx=ctx,
            user_id=owner_id,
            target_type="ai_provider",
            target_id=str(provider_id),
        )
        await self._db.commit()
        return await self.get(owner_id, provider_id)

    async def delete_credential(
        self, owner_id: uuid.UUID, provider_id: uuid.UUID, ctx: RequestContext
    ) -> AIProviderConnection:
        connection = await self.get(owner_id, provider_id)
        if connection.credential is not None:
            await self._db.delete(connection.credential)
            connection.status = "untested"
            self._audit.record(
                "ai.credential.delete",
                "success",
                ctx=ctx,
                user_id=owner_id,
                target_type="ai_provider",
                target_id=str(provider_id),
            )
            await self._db.commit()
        return await self.get(owner_id, provider_id)

    # ------------------------------------------------------- provider round trips
    async def test_connection(
        self, owner_id: uuid.UUID, provider_id: uuid.UUID, ctx: RequestContext
    ) -> tuple[ConnectionCheck, AIProviderConnection]:
        """Lists models (no generation quota spent) and refreshes the catalog in the same call."""
        connection = await self.get(owner_id, provider_id)
        client = self._clients.build(connection)
        try:
            models = await client.list_models()
            check = ConnectionCheck(
                ok=True,
                message=f"Connected. {len(models)} models available.",
                model_count=len(models),
            )
            await self._sync_models(connection, models)
            connection.status = "connected"
            connection.last_error = None
        except AIProviderError as exc:
            check = ConnectionCheck(ok=False, message=exc.message)
            connection.status = "error"
            connection.last_error = exc.message[:500]
        finally:
            await client.aclose()
        connection.last_validated_at = utcnow()
        self._audit.record(
            "ai.provider.test",
            "success" if check.ok else "failure",
            ctx=ctx,
            user_id=owner_id,
            target_type="ai_provider",
            target_id=str(provider_id),
            details={"message": check.message},
        )
        await self._db.commit()
        return check, await self.get(owner_id, provider_id)

    async def add_manual_model(
        self, owner_id: uuid.UUID, provider_id: uuid.UUID, data: ModelCreate
    ) -> AIModelConfiguration:
        connection = await self.get(owner_id, provider_id)
        if any(m.model_id == data.model_id for m in connection.models):
            raise ConflictError("This model is already in the list.", code="ai.model_exists")
        model = AIModelConfiguration(
            provider_id=connection.id,
            model_id=data.model_id,
            display_name=(data.display_name or data.model_id).strip(),
            source="manual",
            capabilities=caps.dump(unknown_capabilities()),
            listed_by_provider=False,
        )
        self._db.add(model)
        await self._db.commit()
        return model

    async def delete_model(self, owner_id: uuid.UUID, model_config_id: uuid.UUID) -> None:
        model = await self.get_model(owner_id, model_config_id)
        await self._db.delete(model)
        await self._db.commit()

    # ------------------------------------------------------------------ helpers
    def _available_spec(self, type_id: str) -> ProviderSpec:
        try:
            spec = self._registry.get(type_id)
        except UnknownProviderTypeError as exc:
            raise ProviderTypeUnavailableError("Unknown provider type.") from exc
        if spec.status != "available":
            raise ProviderTypeUnavailableError(
                f"{spec.display_name} is planned for milestone {spec.milestone}."
            )
        return spec

    async def _checked_base_url(self, spec: ProviderSpec, base_url: str | None) -> str | None:
        if spec.data_location == "local" and not self._clients.settings.local_providers_allowed:
            raise FeatureDisabledError(
                "Local AI providers are disabled on this server (AI_ALLOW_LOCAL_PROVIDERS)."
            )
        if spec.base_url_mode == "none":
            if base_url:
                raise UnsafeBaseUrlError(f"{spec.display_name} does not use a custom endpoint URL.")
            return None
        if not base_url:
            if spec.base_url_mode == "required":
                raise UnsafeBaseUrlError("An endpoint URL is required for this provider.")
            return None
        if spec.data_location == "local":
            return await validate_local_url(base_url)
        return await validate_public_https_url(base_url)

    def _attach_credential(
        self, connection: AIProviderConnection, api_key: str, *, rotated: bool = False
    ) -> None:
        encrypted = self._cipher.encrypt(api_key, associated_data=credential_aad(connection.id))
        now = utcnow()
        connection.credential = AICredential(
            provider_id=connection.id,
            ciphertext=encrypted.ciphertext,
            nonce=encrypted.nonce,
            key_id=encrypted.key_id,
            key_hint=_key_hint(api_key),
            created_at=now,
            rotated_at=now if rotated else None,
        )

    async def _sync_models(self, connection: AIProviderConnection, models: list[ModelInfo]) -> None:
        existing = {m.model_id: m for m in connection.models}
        seen: set[str] = set()
        for info in models:
            seen.add(info.model_id)
            model = existing.get(info.model_id)
            if model is None:
                self._db.add(
                    AIModelConfiguration(
                        provider_id=connection.id,
                        model_id=info.model_id,
                        display_name=info.display_name,
                        source="discovered",
                        capabilities=caps.dump(info.capabilities),
                        input_token_limit=info.input_token_limit,
                        output_token_limit=info.output_token_limit,
                        listed_by_provider=True,
                    )
                )
                continue
            model.display_name = (
                info.display_name if model.source == "discovered" else model.display_name
            )
            model.capabilities = caps.merge_metadata(model.capabilities, info.capabilities)
            model.input_token_limit = info.input_token_limit or model.input_token_limit
            model.output_token_limit = info.output_token_limit or model.output_token_limit
            model.listed_by_provider = True
        for model_id, model in existing.items():
            if model_id not in seen:
                model.listed_by_provider = False
