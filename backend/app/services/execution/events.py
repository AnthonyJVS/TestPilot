"""Execution events: persisted first (ordered by ``seq``), then announced to live subscribers.

The database is the source of truth; notifications are only wake-up hints, so a missed
notification costs latency, never an event. SSE readers resume from ``Last-Event-ID``.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any, Protocol

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.base import utcnow
from app.infrastructure.database.models import ExecutionEvent


class Subscription(Protocol):
    async def wait(self, seconds: float) -> bool:
        """True if a notification arrived within ``seconds``."""
        ...


class EventNotifier(Protocol):
    async def publish(self, execution_id: uuid.UUID) -> None: ...

    def subscribe(
        self, execution_id: uuid.UUID
    ) -> contextlib.AbstractAsyncContextManager[Subscription]: ...


class _MemorySubscription:
    def __init__(self) -> None:
        self.event = asyncio.Event()

    async def wait(self, seconds: float) -> bool:
        try:
            await asyncio.wait_for(self.event.wait(), seconds)
        except TimeoutError:
            return False
        self.event.clear()
        return True


class InMemoryNotifier:
    """Single-process notifier (inline execution mode)."""

    def __init__(self) -> None:
        self._subscribers: dict[uuid.UUID, set[_MemorySubscription]] = defaultdict(set)

    async def publish(self, execution_id: uuid.UUID) -> None:
        for subscription in list(self._subscribers.get(execution_id, ())):
            subscription.event.set()

    @contextlib.asynccontextmanager
    async def subscribe(self, execution_id: uuid.UUID) -> AsyncIterator[Subscription]:
        subscription = _MemorySubscription()
        self._subscribers[execution_id].add(subscription)
        try:
            yield subscription
        finally:
            subscribers = self._subscribers.get(execution_id)
            if subscribers is not None:
                subscribers.discard(subscription)
                if not subscribers:
                    del self._subscribers[execution_id]


def _channel(execution_id: uuid.UUID) -> str:
    return f"exec:{execution_id}"


class _RedisSubscription:
    def __init__(self, pubsub: Any) -> None:
        self._pubsub = pubsub

    async def wait(self, seconds: float) -> bool:
        # get_message returns None early when it swallows a subscribe confirmation: keep waiting.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + seconds
        while (remaining := deadline - loop.time()) > 0:
            message = await self._pubsub.get_message(
                ignore_subscribe_messages=True, timeout=remaining
            )
            if message is not None:
                return True
        return False


class RedisNotifier:
    """Cross-process notifier (Celery workers publish, API processes stream)."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish(self, execution_id: uuid.UUID) -> None:
        await self._redis.publish(_channel(execution_id), "1")

    @contextlib.asynccontextmanager
    async def subscribe(self, execution_id: uuid.UUID) -> AsyncIterator[Subscription]:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(_channel(execution_id))
        try:
            yield _RedisSubscription(pubsub)
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()  # type: ignore[no-untyped-call]


class EventRecorder:
    """Writes events for one execution. Only one writer may own an execution at a time."""

    def __init__(
        self, db: AsyncSession, notifier: EventNotifier, execution_id: uuid.UUID, last_seq: int
    ) -> None:
        self._db = db
        self._notifier = notifier
        self.execution_id = execution_id
        self.seq = last_seq

    def add(
        self,
        type_: str,
        message: str,
        *,
        category: str = "system",
        level: str = "info",
        node_id: str | None = None,
        step_index: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> ExecutionEvent:
        """Stage an event in the current transaction (call ``flush`` to commit and announce)."""
        self.seq += 1
        event = ExecutionEvent(
            execution_id=self.execution_id,
            seq=self.seq,
            ts=utcnow(),
            type=type_,
            category=category,
            level=level,
            node_id=node_id,
            step_index=step_index,
            message=message[:2000],
            data=data or {},
        )
        self._db.add(event)
        return event

    async def emit(self, type_: str, message: str, **kwargs: Any) -> ExecutionEvent:
        event = self.add(type_, message, **kwargs)
        await self.flush()
        return event

    async def flush(self) -> None:
        await self._db.commit()
        await self._notifier.publish(self.execution_id)
