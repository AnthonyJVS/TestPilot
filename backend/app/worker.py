"""Celery orchestrator worker (``celery -A app.worker worker``).

Each task runs one execution on a fresh event loop with its own database engine, talks to the
isolated browser worker over Redis and publishes live events through Redis pub/sub.
"""

from __future__ import annotations

import asyncio
import uuid

from celery import Celery
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.crypto import build_cipher
from app.core.logging import configure_logging
from app.infrastructure.database.session import create_engine, create_session_factory
from app.services.ai.registry import ProviderRegistry
from app.services.execution.browser_client import RedisBrowserClient
from app.services.execution.events import RedisNotifier
from app.services.execution.runtime import EXECUTE_RUN_TASK, ExecutionDispatcher

settings = get_settings()
configure_logging(settings.log_level, settings.log_format)

celery_app = Celery("testpilot", broker=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    worker_prefetch_multiplier=1,
    task_acks_late=False,  # a crashed run is reported as interrupted, never replayed silently
    broker_connection_retry_on_startup=True,
    worker_hijack_root_logger=False,
)


async def _execute(execution_id: uuid.UUID) -> None:
    engine = create_engine(settings.database_url)
    redis = Redis.from_url(settings.redis_url or "", decode_responses=True)
    try:
        dispatcher = ExecutionDispatcher(
            create_session_factory(engine),
            settings,
            build_cipher(settings),
            RedisBrowserClient(redis),
            RedisNotifier(redis),
            ProviderRegistry(),
        )
        await dispatcher.execute(execution_id)
    finally:
        await redis.aclose()
        await engine.dispose()


@celery_app.task(name=EXECUTE_RUN_TASK)  # type: ignore[untyped-decorator,unused-ignore]
def execute_run(execution_id: str) -> None:
    asyncio.run(_execute(uuid.UUID(execution_id)))
