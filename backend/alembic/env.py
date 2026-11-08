"""Alembic environment (async). Uses DATABASE_URL from application settings."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

import app.infrastructure.database.models  # noqa: F401  (register all tables)
from app.core.config import get_settings
from app.infrastructure.database.base import Base
from app.infrastructure.database.session import create_engine

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    return str(config.attributes.get("database_url") or get_settings().database_url)


def _configure(connection: Connection | None = None, url: str | None = None) -> None:
    is_sqlite = (connection.dialect.name if connection is not None else str(url)).startswith(
        "sqlite"
    )
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        render_as_batch=is_sqlite,  # SQLite needs batch mode for ALTER TABLE
        compare_type=True,
        literal_binds=connection is None,
    )


def run_migrations_offline() -> None:
    _configure(url=_database_url())
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_engine(_database_url())
    async with engine.connect() as conn:
        await conn.run_sync(_run_sync)
        await conn.commit()
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
elif (supplied := config.attributes.get("connection")) is not None:
    # Tests pass an already-open sync connection (inside AsyncConnection.run_sync).
    _run_sync(supplied)
else:
    asyncio.run(run_migrations_online())
