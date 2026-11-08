"""Reading and updating a user's AI routing (Simple / Advanced mode, fallback, limits)."""

from __future__ import annotations

import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import AppError
from app.infrastructure.database.models import AIRoutingSettings, AITaskRoute
from app.schemas.ai import EffectiveRouteOut, RouteModelOut, RoutingOut, RoutingUpdate
from app.services.ai.orchestrator import AIOrchestrator
from app.services.ai.registry import ProviderRegistry
from app.services.ai.router import ResolvedRoute, TaskRouter
from app.services.ai.types import TASK_LABELS, TASK_REQUIREMENTS, TaskCategory
from app.services.audit_service import AuditService
from app.services.context import RequestContext


class RoutingValidationError(AppError):
    code = "ai.routing_invalid"
    http_status = 422


class AIRoutingService:
    def __init__(
        self,
        db: AsyncSession,
        registry: ProviderRegistry,
        router: TaskRouter,
        orchestrator: AIOrchestrator,
    ) -> None:
        self._db = db
        self._registry = registry
        self._router = router
        self._orchestrator = orchestrator
        self._audit = AuditService(db)

    async def get(self, owner_id: uuid.UUID) -> RoutingOut:
        settings = await self._router.settings(owner_id)
        routes = await self._router.task_routes(owner_id)
        effective: list[EffectiveRouteOut] = []
        for task in TaskCategory:
            candidate = await self._router.candidate(owner_id, task)
            effective.append(self._effective(task, candidate))
        return RoutingOut(
            mode="advanced" if settings and settings.mode == "advanced" else "simple",
            default_model_id=settings.default_model_id if settings else None,
            task_routes={task.value: model_id for task, model_id in routes.items()},
            fallback_enabled=bool(settings and settings.fallback_enabled),
            fallback_model_id=settings.fallback_model_id if settings else None,
            daily_request_limit=settings.daily_request_limit if settings else None,
            store_payload_previews=settings.store_payload_previews if settings else True,
            requests_today=await self._orchestrator.requests_today(owner_id),
            effective=effective,
        )

    async def update(
        self, owner_id: uuid.UUID, data: RoutingUpdate, ctx: RequestContext
    ) -> RoutingOut:
        referenced = {
            model_id
            for model_id in (
                data.default_model_id,
                data.fallback_model_id,
                *data.task_routes.values(),
            )
            if model_id is not None
        }
        for referenced_id in referenced:
            await self._router.load_model(owner_id, referenced_id)  # 404 unless owned by this user
        if data.fallback_enabled and data.fallback_model_id is None:
            raise RoutingValidationError("Choose a fallback model, or turn fallback off.")
        if data.fallback_enabled and data.fallback_model_id == data.default_model_id:
            raise RoutingValidationError("The fallback model must differ from the default model.")

        settings = await self._router.settings(owner_id)
        if settings is None:
            settings = AIRoutingSettings(owner_id=owner_id)
            self._db.add(settings)
        settings.mode = data.mode
        settings.default_model_id = data.default_model_id
        settings.fallback_enabled = data.fallback_enabled
        settings.fallback_model_id = data.fallback_model_id
        settings.daily_request_limit = data.daily_request_limit
        settings.store_payload_previews = data.store_payload_previews

        await self._db.execute(delete(AITaskRoute).where(AITaskRoute.owner_id == owner_id))
        for task, model_id in data.task_routes.items():
            if model_id is not None:
                self._db.add(
                    AITaskRoute(owner_id=owner_id, task=task.value, model_configuration_id=model_id)
                )
        self._audit.record(
            "ai.routing.update",
            "success",
            ctx=ctx,
            user_id=owner_id,
            details={
                "mode": data.mode,
                "fallback_enabled": data.fallback_enabled,
                "task_routes": len([v for v in data.task_routes.values() if v]),
                "daily_request_limit": data.daily_request_limit,
            },
        )
        await self._db.commit()
        return await self.get(owner_id)

    def _effective(self, task: TaskCategory, route: ResolvedRoute | None) -> EffectiveRouteOut:
        required = [
            "text",
            "structured_output",
            *(c.value for c in TASK_REQUIREMENTS.get(task, ())),
        ]
        if route is None:
            return EffectiveRouteOut(
                task=task,
                label=TASK_LABELS[task],
                source=None,
                model=None,
                required_capabilities=required,
                issues=["No model selected."],
                warnings=[],
            )
        spec = self._registry.get(route.connection.provider_type)
        source = route.source if route.source != "fallback" else "default"
        return EffectiveRouteOut(
            task=task,
            label=TASK_LABELS[task],
            source=source,
            model=RouteModelOut(
                model_configuration_id=route.model.id,
                model_id=route.model.model_id,
                display_name=route.model.display_name,
                provider_id=route.connection.id,
                provider_name=route.connection.name,
                provider_type=route.connection.provider_type,
                data_location=spec.data_location,
            ),
            required_capabilities=required,
            issues=route.issues,
            warnings=route.warnings,
        )
