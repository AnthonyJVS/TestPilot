"""Test fixtures.

The database defaults to a temporary SQLite file; set ``TEST_DATABASE_URL`` (CI does) to run
the same suite against PostgreSQL. The schema is created with the real Alembic migrations.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete

from app.core.config import Settings
from app.infrastructure.database.base import Base
from app.infrastructure.database.session import create_engine
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[1]
CLIENT_IP = "203.0.113.10"
STRONG_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return
    with tempfile.TemporaryDirectory() as tmp:
        yield f"sqlite+aiosqlite:///{Path(tmp, 'test.db').as_posix()}"


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["database_url"] = database_url
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session", autouse=True)
def migrated_database(database_url: str) -> None:
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def make_settings(database_url: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "test",
        "database_url": database_url,
        "redis_url": None,
        "jwt_secret": "test-secret-" + "x" * 40,
        "cookie_secure": False,
        "log_format": "console",
        "log_level": "WARNING",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture
async def _clean_tables(database_url: str) -> AsyncIterator[None]:
    yield
    engine = create_engine(database_url)
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(delete(table))
    await engine.dispose()


ClientFactory = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]


@pytest.fixture
def client_factory(database_url: str, _clean_tables: None) -> ClientFactory:
    @asynccontextmanager
    async def factory(ip: str = CLIENT_IP, **overrides: Any) -> AsyncIterator[httpx.AsyncClient]:
        app = create_app(make_settings(database_url, **overrides))
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app, client=(ip, 50000))
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                yield c

    return factory


@pytest.fixture
async def client(client_factory: ClientFactory) -> AsyncIterator[httpx.AsyncClient]:
    async with client_factory() as c:
        yield c


async def register(
    client: httpx.AsyncClient,
    email: str = "ada@example.com",
    password: str = STRONG_PASSWORD,
    display_name: str = "Ada Lovelace",
) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": display_name},
    )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


CSRF = {"X-Requested-With": "testpilot"}
