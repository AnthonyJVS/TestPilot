"""Real dependency checks for readiness probes and the dashboard."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.schemas.system import DatabaseStatus, DependencyStatus, SystemStatus


async def check_database(engine: AsyncEngine) -> DatabaseStatus:
    started = time.perf_counter()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            latency = round((time.perf_counter() - started) * 1000, 2)
            revision: str | None
            try:
                result = await conn.execute(text("SELECT version_num FROM alembic_version"))
                revision = result.scalar_one_or_none()
            except Exception:
                revision = None
        return DatabaseStatus(
            status="ok",
            latency_ms=latency,
            dialect=engine.dialect.name,
            migration_revision=revision,
        )
    except Exception as exc:
        return DatabaseStatus(
            status="error", dialect=engine.dialect.name, detail=type(exc).__name__
        )


async def check_redis(client: Redis | None) -> DependencyStatus:
    if client is None:
        return DependencyStatus(status="not_configured")
    started = time.perf_counter()
    try:
        await client.ping()
        return DependencyStatus(
            status="ok", latency_ms=round((time.perf_counter() - started) * 1000, 2)
        )
    except Exception as exc:
        return DependencyStatus(status="error", detail=type(exc).__name__)


async def system_status(
    *,
    settings: Settings,
    engine: AsyncEngine,
    redis: Redis | None,
    rate_limiter_backend: str,
    started_at: float,
) -> SystemStatus:
    return SystemStatus(
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
        server_time=datetime.now(UTC),
        uptime_seconds=round(time.monotonic() - started_at, 1),
        database=await check_database(engine),
        redis=await check_redis(redis),
        rate_limiter_backend=rate_limiter_backend,
        registration_enabled=settings.allow_registration,
    )
