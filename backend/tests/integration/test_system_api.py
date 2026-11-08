from __future__ import annotations

import httpx
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection

from app.infrastructure.database.base import Base
from app.infrastructure.database.session import create_engine
from tests.conftest import bearer, register


async def test_liveness(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_reports_real_dependency_state(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok", "redis": "not_configured"},
    }


async def test_readiness_fails_when_redis_is_unreachable(client_factory) -> None:  # type: ignore[no-untyped-def]
    async with client_factory(redis_url="redis://127.0.0.1:1/0") as client:
        response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["redis"] == "error"


async def test_system_status_requires_auth_and_reports_migration(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/system/status")).status_code == 401

    access = (await register(client)).json()["access_token"]
    response = await client.get("/api/v1/system/status", headers=bearer(access))
    assert response.status_code == 200
    body = response.json()
    assert body["database"]["status"] == "ok"
    assert body["database"]["migration_revision"] == "0001"
    assert body["redis"]["status"] == "not_configured"
    assert body["rate_limiter_backend"] == "in_memory"
    assert body["environment"] == "test"


async def test_security_headers_present(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-request-id"]


async def test_unknown_route_uses_error_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "resource.not_found"


async def test_models_and_migrations_are_in_sync(database_url: str) -> None:
    def diff(conn: Connection) -> list[object]:
        return list(compare_metadata(MigrationContext.configure(conn), Base.metadata))

    engine = create_engine(database_url)
    async with engine.connect() as conn:
        differences = await conn.run_sync(diff)
    await engine.dispose()
    assert differences == [], f"Models differ from migrations: {differences}"
