"""Redis request/response host for the browser engine (the ``browser-worker`` container).

Queues:

* ``bw:requests`` — shared queue for ``info`` and ``open``; any worker with free capacity takes it.
* ``bw:worker:<worker_id>`` — ``step``/``close`` for sessions owned by that worker (sessions are
  stateful, so follow-up commands are routed to the worker that opened them).
* Replies go to the per-request ``reply_to`` list and expire after a minute.

Requests past their deadline are dropped: the caller has already given up.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from pydantic import ValidationError
from redis.asyncio import Redis

from browser_worker.engine import BrowserEngine
from browser_worker.protocol import (
    REPLY_PREFIX,
    REQUEST_QUEUE,
    CloseSessionParams,
    FrameParams,
    OpenSessionParams,
    RpcError,
    RpcRequest,
    RpcResponse,
    StepParams,
    WorkerError,
    worker_queue,
)

logger = logging.getLogger("browser_worker")

REPLY_TTL_SECONDS = 60


async def dispatch(engine: BrowserEngine, request: RpcRequest) -> RpcResponse:
    try:
        result: Any
        match request.method:
            case "info":
                result = engine.info()
            case "open":
                result = await engine.open(OpenSessionParams.model_validate(request.params))
            case "step":
                result = await engine.step(StepParams.model_validate(request.params))
            case "frame":
                result = await engine.frame(FrameParams.model_validate(request.params))
            case "close":
                result = await engine.close(CloseSessionParams.model_validate(request.params))
        return RpcResponse(id=request.id, ok=True, result=result.model_dump(mode="json"))
    except WorkerError as exc:
        error = RpcError(code=exc.code, message=exc.message[:2000])
    except ValidationError as exc:
        error = RpcError(code="request.invalid", message=str(exc)[:2000])
    except Exception:
        logger.exception("Browser worker request failed")
        error = RpcError(code="internal", message="The browser worker hit an error.")
    return RpcResponse(id=request.id, ok=False, error=error)


class RedisWorkerServer:
    def __init__(self, redis: Redis, engine: BrowserEngine) -> None:
        self.redis = redis
        self.engine = engine
        self._tasks: set[asyncio.Task[None]] = set()
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        self._stopping.set()

    async def serve(self) -> None:
        own = worker_queue(self.engine.worker_id)
        logger.info("Browser worker %s listening", self.engine.worker_id)
        reaper = asyncio.create_task(self._reap())
        try:
            while not self._stopping.is_set():
                keys = [own, REQUEST_QUEUE] if self.engine.has_capacity else [own]
                item = await self.redis.brpop(keys, timeout=1)
                if item is None:
                    continue
                task = asyncio.create_task(self._handle(item[1]))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        finally:
            reaper.cancel()
            for task in list(self._tasks):
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    async def _handle(self, raw: str | bytes) -> None:
        try:
            request = RpcRequest.model_validate_json(raw)
        except ValidationError:
            logger.warning("Dropping malformed browser worker request")
            return
        if request.deadline < time.time() or not request.reply_to.startswith(REPLY_PREFIX):
            return
        response = await dispatch(self.engine, request)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.lpush(request.reply_to, response.model_dump_json())
            pipe.expire(request.reply_to, REPLY_TTL_SECONDS)
            await pipe.execute()

    async def _reap(self) -> None:
        while True:
            await asyncio.sleep(15)
            await self.engine.reap_idle()
