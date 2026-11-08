"""Resolves which provider/model handles an AI task.

Precedence (highest first):
1. explicit override (e.g. a Workflow Studio AI node's own model, milestone 5)
2. Advanced mode: the route configured for the task category
3. the default model (Simple mode uses it for every task)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.exceptions import NotFoundError
from app.infrastructure.database.models import (
    AIModelConfiguration,
    AIProviderConnection,
    AIRoutingSettings,
    AITaskRoute,
)
from app.services.ai import capabilities as caps
from app.services.ai.exceptions import (
    CapabilityMissingError,
    CredentialMissingError,
    RoutingNotConfiguredError,
)
from app.services.ai.registry import ProviderRegistry
from app.services.ai.types import (
    TASK_LABELS,
    TASK_REQUIREMENTS,
    CapabilityStatus,
    TaskCategory,
)

RouteSource = Literal["override", "task_route", "default", "fallback"]


@dataclass(slots=True)
class ResolvedRoute:
    task: TaskCategory
    model: AIModelConfiguration
    connection: AIProviderConnection
    source: RouteSource
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class TaskRouter:
    def __init__(self, db: AsyncSession, registry: ProviderRegistry) -> None:
        self._db = db
        self._registry = registry

    async def settings(self, owner_id: uuid.UUID) -> AIRoutingSettings | None:
        result = await self._db.execute(
            select(AIRoutingSettings).where(AIRoutingSettings.owner_id == owner_id)
        )
        return result.scalar_one_or_none()

    async def task_routes(self, owner_id: uuid.UUID) -> dict[TaskCategory, uuid.UUID]:
        result = await self._db.execute(select(AITaskRoute).where(AITaskRoute.owner_id == owner_id))
        routes: dict[TaskCategory, uuid.UUID] = {}
        for route in result.scalars():
            try:
                routes[TaskCategory(route.task)] = route.model_configuration_id
            except ValueError:
                continue
        return routes

    async def load_model(
        self, owner_id: uuid.UUID, model_config_id: uuid.UUID
    ) -> AIModelConfiguration:
        result = await self._db.execute(
            select(AIModelConfiguration)
            .join(AIProviderConnection)
            .options(
                selectinload(AIModelConfiguration.provider).selectinload(
                    AIProviderConnection.credential
                )
            )
            .where(
                AIModelConfiguration.id == model_config_id,
                AIProviderConnection.owner_id == owner_id,
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError("Model not found.")
        return model

    async def candidate(
        self, owner_id: uuid.UUID, task: TaskCategory, *, override_model_id: uuid.UUID | None = None
    ) -> ResolvedRoute | None:
        """The route that would be used, with issues/warnings collected (never raises)."""
        if override_model_id is not None:
            model = await self.load_model(owner_id, override_model_id)
            return self._annotate(ResolvedRoute(task, model, model.provider, "override"))
        settings = await self.settings(owner_id)
        if settings is None:
            return None
        if settings.mode == "advanced":
            routes = await self.task_routes(owner_id)
            if task in routes:
                model = await self.load_model(owner_id, routes[task])
                return self._annotate(ResolvedRoute(task, model, model.provider, "task_route"))
        if settings.default_model_id is None:
            return None
        model = await self.load_model(owner_id, settings.default_model_id)
        return self._annotate(ResolvedRoute(task, model, model.provider, "default"))

    async def resolve(
        self, owner_id: uuid.UUID, task: TaskCategory, *, override_model_id: uuid.UUID | None = None
    ) -> ResolvedRoute:
        route = await self.candidate(owner_id, task, override_model_id=override_model_id)
        if route is None:
            raise RoutingNotConfiguredError()
        self.ensure_usable(route)
        return route

    async def resolve_fallback(
        self, owner_id: uuid.UUID, task: TaskCategory, primary: ResolvedRoute
    ) -> ResolvedRoute | None:
        settings = await self.settings(owner_id)
        if settings is None or not settings.fallback_enabled or settings.fallback_model_id is None:
            return None
        if settings.fallback_model_id == primary.model.id:
            return None
        model = await self.load_model(owner_id, settings.fallback_model_id)
        route = self._annotate(ResolvedRoute(task, model, model.provider, "fallback"))
        return None if route.issues else route

    def ensure_usable(self, route: ResolvedRoute) -> None:
        if route.issues:
            first = route.issues[0]
            if "API key" in first:
                raise CredentialMissingError(first)
            raise CapabilityMissingError(first)

    def _annotate(self, route: ResolvedRoute) -> ResolvedRoute:
        spec = self._registry.get(route.connection.provider_type)
        if spec.status != "available":
            route.issues.append(f"{spec.display_name} is not available yet.")
        if spec.requires_api_key and route.connection.credential is None:
            route.issues.append(f"The connection '{route.connection.name}' has no API key.")
        if route.connection.status == "error":
            route.warnings.append(f"The last connection test for '{route.connection.name}' failed.")
        current = caps.load(route.model.capabilities)
        for capability in TASK_REQUIREMENTS.get(route.task, ()):
            status = current[capability].status
            label = TASK_LABELS[route.task]
            if status == CapabilityStatus.UNSUPPORTED:
                route.issues.append(
                    f"{label} needs {capability.value} support, which {route.model.model_id} lacks."
                )
            elif status == CapabilityStatus.UNKNOWN:
                route.warnings.append(
                    f"{capability.value} support for {route.model.model_id} is not verified yet. "
                    "Run the routing check to verify it."
                )
        return route
