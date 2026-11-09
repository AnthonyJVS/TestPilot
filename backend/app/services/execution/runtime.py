"""Execution runtime wiring: job queue, browser client and event notifier per deployment mode.

| Mode (settings)                         | Jobs run in          | Browser runs in              |
| --------------------------------------- | -------------------- | ---------------------------- |
| ``inline`` + ``thread`` (development)   | API process (asyncio)| API process (engine thread)  |
| ``celery`` + ``redis`` (production)     | Celery worker        | isolated browser-worker      |
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.crypto import SecretCipher
from app.infrastructure.database.base import utcnow
from app.infrastructure.database.models import NodeExecution, TestExecution, WorkflowExecution
from app.services.ai.registry import ProviderRegistry
from app.services.execution.browser_client import (
    BrowserClient,
    RedisBrowserClient,
    ThreadedBrowserClient,
)
from app.services.execution.events import EventNotifier, InMemoryNotifier, RedisNotifier
from app.services.execution.orchestrator import TestRunOrchestrator

logger = logging.getLogger(__name__)

EXECUTE_RUN_TASK = "testpilot.execute_run"


class JobQueue(Protocol):
    async def enqueue(self, execution_id: uuid.UUID) -> None: ...

    async def aclose(self) -> None: ...


class InlineJobQueue:
    """Runs executions as asyncio tasks in this process (development only)."""

    def __init__(self, runner: Callable[[uuid.UUID], Awaitable[None]], concurrency: int) -> None:
        self._runner = runner
        self._semaphore = asyncio.Semaphore(concurrency)
        self._tasks: set[asyncio.Task[None]] = set()

    async def enqueue(self, execution_id: uuid.UUID) -> None:
        task = asyncio.create_task(self._run(execution_id), name=f"execution-{execution_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, execution_id: uuid.UUID) -> None:
        async with self._semaphore:
            try:
                await self._runner(execution_id)
            except Exception:
                logger.exception("Inline execution %s failed", execution_id)

    async def drain(self) -> None:
        """Wait for queued executions (tests)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def aclose(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)


class CeleryJobQueue:
    def __init__(self, redis_url: str) -> None:
        from celery import Celery

        self._celery = Celery("testpilot", broker=redis_url)

    async def enqueue(self, execution_id: uuid.UUID) -> None:
        await asyncio.to_thread(self._celery.send_task, EXECUTE_RUN_TASK, args=[str(execution_id)])

    async def aclose(self) -> None:
        await asyncio.to_thread(self._celery.close)


class ExecutionDispatcher:
    """Routes an execution to the orchestrator for its kind (test run or workflow)."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        cipher: SecretCipher,
        browser: BrowserClient,
        notifier: EventNotifier,
        providers: ProviderRegistry,
    ) -> None:
        from app.services.workflows.catalog import node_registry
        from app.services.workflows.engine import WorkflowOrchestrator

        self._sf = session_factory
        self.test_runs = TestRunOrchestrator(session_factory, settings, cipher, browser, notifier)
        self.workflows = WorkflowOrchestrator(
            session_factory, settings, cipher, browser, notifier, providers, node_registry()
        )

    async def execute(self, execution_id: uuid.UUID) -> None:
        async with self._sf() as db:
            kind = await db.scalar(
                select(WorkflowExecution.kind).where(WorkflowExecution.id == execution_id)
            )
        if kind == "workflow":
            await self.workflows.execute(execution_id)
        elif kind is not None:
            await self.test_runs.execute(execution_id)


@dataclass
class ExecutionRuntime:
    settings: Settings
    browser: BrowserClient
    notifier: EventNotifier
    jobs: JobQueue
    artifacts_root: Path

    @property
    def isolated(self) -> bool:
        return self.settings.browser_transport == "redis"

    async def aclose(self) -> None:
        await self.jobs.aclose()
        await self.browser.aclose()


def build_browser_client(settings: Settings, redis: Redis | None) -> BrowserClient:
    if settings.browser_transport == "redis":
        assert redis is not None  # enforced by settings validation
        return RedisBrowserClient(redis)
    return ThreadedBrowserClient(
        Path(settings.artifacts_dir), max_sessions=settings.browser_max_sessions
    )


def build_runtime(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    cipher: SecretCipher,
    redis: Redis | None,
    providers: ProviderRegistry,
) -> ExecutionRuntime:
    browser = build_browser_client(settings, redis)
    notifier: EventNotifier = RedisNotifier(redis) if redis is not None else InMemoryNotifier()
    jobs: JobQueue
    if settings.execution_mode == "celery":
        assert settings.redis_url is not None
        jobs = CeleryJobQueue(settings.redis_url)
    else:
        dispatcher = ExecutionDispatcher(
            session_factory, settings, cipher, browser, notifier, providers
        )
        jobs = InlineJobQueue(dispatcher.execute, settings.max_concurrent_runs)
        logger.warning(
            "EXECUTION_MODE=inline: test runs execute inside the API process%s. Development only.",
            "" if settings.browser_transport == "redis" else " with an unisolated browser",
        )
    root = Path(settings.artifacts_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return ExecutionRuntime(settings, browser, notifier, jobs, root)


async def interrupt_orphaned_runs(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """Inline mode: runs that were queued/running when the process stopped can never finish."""
    async with session_factory() as db:
        now = utcnow()
        result = await db.execute(
            update(WorkflowExecution)
            .where(WorkflowExecution.status.in_(("queued", "running")))
            .values(
                status="error",
                finished_at=now,
                error_code="run.interrupted",
                error_message="The server restarted before the run finished.",
            )
            .returning(WorkflowExecution.id)
        )
        ids = list(result.scalars())
        if ids:
            await db.execute(
                update(TestExecution)
                .where(TestExecution.execution_id.in_(ids))
                .values(status="error", finished_at=now)
            )
            await db.execute(
                update(NodeExecution)
                .where(
                    NodeExecution.execution_id.in_(ids),
                    NodeExecution.status.in_(("waiting", "running")),
                )
                .values(status="cancelled")
            )
        await db.commit()
        return len(ids)
