"""Dependency wiring for the AI services."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.api.dependencies import DbSession, SettingsDep
from app.core.crypto import SecretCipher
from app.services.ai.client_factory import ProviderClientFactory
from app.services.ai.orchestrator import AIOrchestrator
from app.services.ai.provider_service import AIProviderService
from app.services.ai.registry import ProviderRegistry
from app.services.ai.router import TaskRouter
from app.services.ai.routing_service import AIRoutingService


def get_provider_registry(request: Request) -> ProviderRegistry:
    registry: ProviderRegistry = request.app.state.provider_registry
    return registry


def get_cipher(request: Request) -> SecretCipher:
    cipher: SecretCipher = request.app.state.cipher
    return cipher


Registry = Annotated[ProviderRegistry, Depends(get_provider_registry)]
Cipher = Annotated[SecretCipher, Depends(get_cipher)]


def get_client_factory(
    settings: SettingsDep, registry: Registry, cipher: Cipher
) -> ProviderClientFactory:
    return ProviderClientFactory(settings, registry, cipher)


Clients = Annotated[ProviderClientFactory, Depends(get_client_factory)]


def get_provider_service(
    db: DbSession, registry: Registry, cipher: Cipher, clients: Clients
) -> AIProviderService:
    return AIProviderService(db, registry, cipher, clients)


def get_task_router(db: DbSession, registry: Registry) -> TaskRouter:
    return TaskRouter(db, registry)


Router = Annotated[TaskRouter, Depends(get_task_router)]


def get_orchestrator(
    request: Request, db: DbSession, settings: SettingsDep, router: Router, clients: Clients
) -> AIOrchestrator:
    sleep = getattr(request.app.state, "ai_sleep", None)
    if sleep is not None:  # tests replace the sleep function
        return AIOrchestrator(db, settings, router, clients, sleep=sleep)
    return AIOrchestrator(db, settings, router, clients)


def get_routing_service(
    db: DbSession,
    registry: Registry,
    router: Router,
    orchestrator: Annotated[AIOrchestrator, Depends(get_orchestrator)],
) -> AIRoutingService:
    return AIRoutingService(db, registry, router, orchestrator)
