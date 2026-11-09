"""Clients for the browser worker. Both speak the same typed protocol.

* ``RedisBrowserClient`` — production: commands go over Redis to the isolated ``browser-worker``
  container, which has no database access and no AI keys.
* ``ThreadedBrowserClient`` — development without Docker/Redis: the same engine runs on a
  dedicated thread (with its own event loop) inside this process. It offers no isolation and the
  settings validator refuses it in production.
"""

from __future__ import annotations

import asyncio
import math
import secrets
import sys
import threading
import time
from collections.abc import Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from pydantic import BaseModel
from redis.asyncio import Redis

from browser_worker.protocol import (
    REPLY_PREFIX,
    REQUEST_QUEUE,
    CloseSessionParams,
    CloseSessionResult,
    Method,
    OpenSessionParams,
    OpenSessionResult,
    RpcRequest,
    RpcResponse,
    StepParams,
    StepResult,
    WorkerError,
    WorkerInfo,
    worker_queue,
)

if TYPE_CHECKING:
    from browser_worker.engine import BrowserEngine

T = TypeVar("T")

INFO_TIMEOUT_SECONDS = 5.0
OPEN_TIMEOUT_SECONDS = 60.0
CLOSE_TIMEOUT_SECONDS = 60.0


class BrowserClient(Protocol):
    async def info(self) -> WorkerInfo: ...

    async def open(self, params: OpenSessionParams) -> OpenSessionResult: ...

    async def step(
        self, params: StepParams, *, worker_id: str, wait_seconds: float
    ) -> StepResult: ...

    async def close(self, params: CloseSessionParams, *, worker_id: str) -> CloseSessionResult: ...

    async def aclose(self) -> None: ...


class ThreadedBrowserClient:
    def __init__(self, artifacts_root: Path, *, max_sessions: int) -> None:
        self._artifacts_root = artifacts_root
        self._max_sessions = max_sessions
        self._engine: BrowserEngine | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._reaper: Any = None
        self._lock = threading.Lock()

    def _start(self) -> None:
        with self._lock:
            if self._engine is not None:
                return
            # Playwright needs subprocess support: the Proactor loop on Windows.
            loop = (
                asyncio.ProactorEventLoop()  # type: ignore[attr-defined,unused-ignore]
                if sys.platform == "win32"
                else asyncio.new_event_loop()
            )
            # Imported lazily: Playwright is only installed where browsers run.
            from browser_worker.engine import BrowserEngine

            thread = threading.Thread(target=loop.run_forever, name="browser-engine", daemon=True)
            thread.start()
            engine = BrowserEngine(self._artifacts_root, max_sessions=self._max_sessions)
            asyncio.run_coroutine_threadsafe(engine.start(), loop).result(timeout=60)
            self._reaper = asyncio.run_coroutine_threadsafe(self._reap(engine), loop)
            self._loop, self._thread, self._engine = loop, thread, engine

    @staticmethod
    async def _reap(engine: BrowserEngine) -> None:
        while True:
            await asyncio.sleep(15)
            await engine.reap_idle()

    async def _call(self, factory: Any) -> Any:
        if self._engine is None:
            await asyncio.to_thread(self._start)
        assert self._engine is not None and self._loop is not None
        coro: Coroutine[Any, Any, Any] = factory(self._engine)
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return await asyncio.wrap_future(future)

    async def info(self) -> WorkerInfo:
        async def run(engine: BrowserEngine) -> WorkerInfo:
            return engine.info()

        result: WorkerInfo = await self._call(run)
        return result

    async def open(self, params: OpenSessionParams) -> OpenSessionResult:
        result: OpenSessionResult = await self._call(lambda engine: engine.open(params))
        return result

    async def step(self, params: StepParams, *, worker_id: str, wait_seconds: float) -> StepResult:
        try:
            result: StepResult = await asyncio.wait_for(
                self._call(lambda engine: engine.step(params)), wait_seconds
            )
        except TimeoutError as exc:
            raise WorkerError("worker.timeout", "The browser did not respond in time.") from exc
        return result

    async def close(self, params: CloseSessionParams, *, worker_id: str) -> CloseSessionResult:
        result: CloseSessionResult = await self._call(lambda engine: engine.close(params))
        return result

    async def aclose(self) -> None:
        engine, loop, thread = self._engine, self._loop, self._thread
        if engine is None or loop is None or thread is None:
            return
        self._engine = None
        if self._reaper is not None:
            self._reaper.cancel()
        try:
            await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(engine.stop(), loop))
        finally:
            loop.call_soon_threadsafe(loop.stop)
            await asyncio.to_thread(thread.join, 10)
            loop.close()


class RedisBrowserClient:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def _call(
        self,
        method: Method,
        params: BaseModel | None,
        *,
        queue: str,
        wait_seconds: float,
        result_type: type[T],
    ) -> T:
        request_id = secrets.token_hex(16)
        reply_to = f"{REPLY_PREFIX}{request_id}"
        request = RpcRequest(
            id=request_id,
            method=method,
            params=params.model_dump(mode="json") if params else {},
            reply_to=reply_to,
            deadline=time.time() + wait_seconds,
        )
        await self._redis.lpush(queue, request.model_dump_json())
        item = await self._redis.brpop([reply_to], timeout=max(1, math.ceil(wait_seconds)))
        if item is None:
            raise WorkerError(
                "worker.timeout",
                "No browser worker answered in time. Check that the browser-worker service is "
                "running.",
            )
        response = RpcResponse.model_validate_json(item[1])
        if not response.ok:
            error = response.error
            raise WorkerError(
                error.code if error else "internal", error.message if error else "Worker error."
            )
        return result_type.model_validate(response.result)  # type: ignore[attr-defined, no-any-return]

    async def info(self) -> WorkerInfo:
        return await self._call(
            "info",
            None,
            queue=REQUEST_QUEUE,
            wait_seconds=INFO_TIMEOUT_SECONDS,
            result_type=WorkerInfo,
        )

    async def open(self, params: OpenSessionParams) -> OpenSessionResult:
        return await self._call(
            "open",
            params,
            queue=REQUEST_QUEUE,
            wait_seconds=OPEN_TIMEOUT_SECONDS,
            result_type=OpenSessionResult,
        )

    async def step(self, params: StepParams, *, worker_id: str, wait_seconds: float) -> StepResult:
        return await self._call(
            "step",
            params,
            queue=worker_queue(worker_id),
            wait_seconds=wait_seconds,
            result_type=StepResult,
        )

    async def close(self, params: CloseSessionParams, *, worker_id: str) -> CloseSessionResult:
        return await self._call(
            "close",
            params,
            queue=worker_queue(worker_id),
            wait_seconds=CLOSE_TIMEOUT_SECONDS,
            result_type=CloseSessionResult,
        )

    async def aclose(self) -> None:
        return None
