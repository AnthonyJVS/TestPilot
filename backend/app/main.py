"""FastAPI application factory."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.api.errors import install_error_handlers
from app.api.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.api.router import api_router
from app.api.routes import health
from app.core.config import Settings, get_settings
from app.core.crypto import build_cipher
from app.core.logging import configure_logging
from app.infrastructure.cache.rate_limiter import (
    InMemoryRateLimiter,
    RateLimiter,
    RedisRateLimiter,
)
from app.infrastructure.database.session import create_engine, create_session_factory
from app.services.ai.registry import ProviderRegistry

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None, *, provider_registry: ProviderRegistry | None = None
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)
    cipher = build_cipher(settings)  # fail fast on malformed ENCRYPTION_KEYS
    registry = provider_registry or ProviderRegistry()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url, echo=settings.database_echo)
        redis: Redis | None = None
        limiter: RateLimiter
        if settings.redis_url:
            redis = Redis.from_url(settings.redis_url, decode_responses=True)
            limiter = RedisRateLimiter(redis)
        else:
            limiter = InMemoryRateLimiter()
            logger.warning("REDIS_URL not set; using in-memory rate limiter (single process only).")

        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.redis = redis
        app.state.rate_limiter = limiter
        app.state.cipher = cipher
        app.state.provider_registry = registry
        app.state.started_at = time.monotonic()
        logger.info(
            "TestPilot API started",
            extra={"environment": settings.app_env, "database": engine.dialect.name},
        )
        try:
            yield
        finally:
            if redis is not None:
                await redis.aclose()
            await engine.dispose()

    docs = settings.enable_api_docs
    app = FastAPI(
        title="TestPilot API",
        version=settings.app_version,
        description="Multi-LLM autonomous web testing platform.",
        lifespan=lifespan,
        docs_url="/api/docs" if docs else None,
        redoc_url="/api/redoc" if docs else None,
        openapi_url="/api/openapi.json" if docs else None,
    )

    # Order: the last added middleware runs first.
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-Request-ID"],
        )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)

    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(api_router)
    return app


def app_factory() -> FastAPI:
    """Entry point for ``uvicorn --factory app.main:app_factory``."""
    return create_app()
