"""AI providers, model catalog, routing, routing checks and the AI request log."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select

from app.api.dependencies import Ctx, CurrentUser, DbSession
from app.api.dependencies.ai import (
    get_orchestrator,
    get_provider_registry,
    get_provider_service,
    get_routing_service,
)
from app.domain.exceptions import NotFoundError
from app.infrastructure.database.models import AIModelConfiguration, AIProviderConnection, AIRequest
from app.schemas.ai import (
    AIRequestOut,
    AIRequestPage,
    CapabilityOut,
    ConnectionTestOut,
    CredentialOut,
    CredentialUpdate,
    ModelCreate,
    ModelOut,
    ProviderCreate,
    ProviderOut,
    ProviderTypeOut,
    ProviderUpdate,
    RoutingOut,
    RoutingUpdate,
    TaskCheckOut,
)
from app.services.ai import capabilities as caps
from app.services.ai.orchestrator import AIOrchestrator
from app.services.ai.provider_service import AIProviderService
from app.services.ai.registry import ProviderRegistry
from app.services.ai.routing_service import AIRoutingService
from app.services.ai.task_checks import TaskCheckResult, run_task_check
from app.services.ai.types import TaskCategory
from app.services.audit_service import decode_cursor, encode_cursor

router = APIRouter(prefix="/ai", tags=["ai"])

Registry = Annotated[ProviderRegistry, Depends(get_provider_registry)]
Providers = Annotated[AIProviderService, Depends(get_provider_service)]
Routing = Annotated[AIRoutingService, Depends(get_routing_service)]
Orchestrator = Annotated[AIOrchestrator, Depends(get_orchestrator)]


def _model_out(model: AIModelConfiguration) -> ModelOut:
    return ModelOut(
        id=model.id,
        provider_id=model.provider_id,
        model_id=model.model_id,
        display_name=model.display_name,
        source=model.source,
        # Normalised: every capability present, "unknown" unless there is evidence.
        capabilities={
            cap.value: CapabilityOut(status=value.status.value, source=value.source.value)
            for cap, value in caps.load(model.capabilities).items()
        },
        input_token_limit=model.input_token_limit,
        output_token_limit=model.output_token_limit,
        listed_by_provider=model.listed_by_provider,
    )


def _provider_out(connection: AIProviderConnection, registry: ProviderRegistry) -> ProviderOut:
    spec = registry.get(connection.provider_type)
    credential = connection.credential
    return ProviderOut(
        id=connection.id,
        provider_type=connection.provider_type,
        provider_display_name=spec.display_name,
        data_location=spec.data_location,
        name=connection.name,
        base_url=connection.base_url,
        status=connection.status,
        last_validated_at=connection.last_validated_at,
        last_error=connection.last_error,
        credential=(
            CredentialOut(
                key_hint=credential.key_hint,
                created_at=credential.created_at,
                rotated_at=credential.rotated_at,
            )
            if credential
            else None
        ),
        models=[_model_out(m) for m in connection.models],
        created_at=connection.created_at,
    )


def _check_out(result: TaskCheckResult) -> TaskCheckOut:
    return TaskCheckOut(
        task=result.task,
        label=result.label,
        status=result.status,
        message=result.message,
        provider_type=result.provider_type,
        model=result.model,
        actual_model=result.actual_model,
        latency_ms=result.latency_ms,
        total_tokens=result.total_tokens,
        ai_request_id=result.ai_request_id,
    )


# ------------------------------------------------------------------ catalog


@router.get("/provider-types", response_model=list[ProviderTypeOut])
async def list_provider_types(_: CurrentUser, registry: Registry) -> list[ProviderTypeOut]:
    return [
        ProviderTypeOut(
            type_id=spec.type_id,
            display_name=spec.display_name,
            description=spec.description,
            status=spec.status,
            data_location=spec.data_location,
            requires_api_key=spec.requires_api_key,
            base_url_mode=spec.base_url_mode,
            supports_model_listing=spec.supports_model_listing,
            key_help_url=spec.key_help_url,
            milestone=spec.milestone,
        )
        for spec in registry.all()
    ]


# -------------------------------------------------------------- connections


@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(
    user: CurrentUser, providers: Providers, registry: Registry
) -> list[ProviderOut]:
    return [_provider_out(c, registry) for c in await providers.list_connections(user.id)]


@router.post("/providers", response_model=ProviderOut, status_code=status.HTTP_201_CREATED)
async def create_provider(
    body: ProviderCreate, user: CurrentUser, providers: Providers, registry: Registry, ctx: Ctx
) -> ProviderOut:
    return _provider_out(await providers.create(user.id, body, ctx), registry)


@router.get("/providers/{provider_id}", response_model=ProviderOut)
async def get_provider(
    provider_id: uuid.UUID, user: CurrentUser, providers: Providers, registry: Registry
) -> ProviderOut:
    return _provider_out(await providers.get(user.id, provider_id), registry)


@router.patch("/providers/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: uuid.UUID,
    body: ProviderUpdate,
    user: CurrentUser,
    providers: Providers,
    registry: Registry,
    ctx: Ctx,
) -> ProviderOut:
    return _provider_out(await providers.update(user.id, provider_id, body, ctx), registry)


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: uuid.UUID, user: CurrentUser, providers: Providers, ctx: Ctx
) -> Response:
    await providers.delete(user.id, provider_id, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/providers/{provider_id}/credential", response_model=ProviderOut)
async def set_credential(
    provider_id: uuid.UUID,
    body: CredentialUpdate,
    user: CurrentUser,
    providers: Providers,
    registry: Registry,
    ctx: Ctx,
) -> ProviderOut:
    connection = await providers.set_credential(
        user.id, provider_id, body.api_key.get_secret_value(), ctx
    )
    return _provider_out(connection, registry)


@router.delete("/providers/{provider_id}/credential", response_model=ProviderOut)
async def delete_credential(
    provider_id: uuid.UUID, user: CurrentUser, providers: Providers, registry: Registry, ctx: Ctx
) -> ProviderOut:
    return _provider_out(await providers.delete_credential(user.id, provider_id, ctx), registry)


@router.post("/providers/{provider_id}/test", response_model=ConnectionTestOut)
async def test_provider(
    provider_id: uuid.UUID, user: CurrentUser, providers: Providers, registry: Registry, ctx: Ctx
) -> ConnectionTestOut:
    check, connection = await providers.test_connection(user.id, provider_id, ctx)
    return ConnectionTestOut(
        ok=check.ok,
        message=check.message,
        model_count=check.model_count,
        provider=_provider_out(connection, registry),
    )


@router.post(
    "/providers/{provider_id}/models",
    response_model=ModelOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_model(
    provider_id: uuid.UUID, body: ModelCreate, user: CurrentUser, providers: Providers
) -> ModelOut:
    return _model_out(await providers.add_manual_model(user.id, provider_id, body))


@router.delete("/models/{model_config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    model_config_id: uuid.UUID, user: CurrentUser, providers: Providers
) -> Response:
    await providers.delete_model(user.id, model_config_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ routing


@router.get("/routing", response_model=RoutingOut)
async def get_routing(user: CurrentUser, routing: Routing) -> RoutingOut:
    return await routing.get(user.id)


@router.put("/routing", response_model=RoutingOut)
async def update_routing(
    body: RoutingUpdate, user: CurrentUser, routing: Routing, ctx: Ctx
) -> RoutingOut:
    return await routing.update(user.id, body, ctx)


@router.post("/routing/check/{task}", response_model=TaskCheckOut)
async def check_task_route(
    task: TaskCategory, user: CurrentUser, orchestrator: Orchestrator, db: DbSession
) -> TaskCheckOut:
    """Runs one real, minimal AI call for the task's route. Spends provider quota."""
    result = await run_task_check(orchestrator, user.id, task)
    await db.commit()  # persist capability evidence learned by the check
    return _check_out(result)


# -------------------------------------------------------------- request log


@router.get("/requests/{request_id}", response_model=AIRequestOut)
async def get_ai_request(request_id: uuid.UUID, user: CurrentUser, db: DbSession) -> AIRequestOut:
    """One AI call with its sanitized previews (Execution Center inspector)."""
    record = await db.scalar(
        select(AIRequest).where(AIRequest.id == request_id, AIRequest.owner_id == user.id)
    )
    if record is None:
        raise NotFoundError("AI request not found.")
    return AIRequestOut.model_validate(record)


@router.get("/requests", response_model=AIRequestPage)
async def list_ai_requests(
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> AIRequestPage:
    stmt = select(AIRequest).where(AIRequest.owner_id == user.id)
    if cursor:
        started, entry_id = decode_cursor(cursor)
        stmt = stmt.where(
            (AIRequest.started_at < started)
            | ((AIRequest.started_at == started) & (AIRequest.id < entry_id))
        )
    stmt = stmt.order_by(AIRequest.started_at.desc(), AIRequest.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].started_at, rows[-1].id)
    return AIRequestPage(
        items=[AIRequestOut.model_validate(r) for r in rows], next_cursor=next_cursor
    )
