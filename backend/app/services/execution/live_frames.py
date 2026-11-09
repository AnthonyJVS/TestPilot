"""Throttled live frames while a browser step runs (docs/EXECUTION_CENTER.md §5).

A step that finishes quickly produces no live frames: the first one is taken after
``START_AFTER_SECONDS``. The streamer stops through an event (never by cancelling it in the
middle of a database write) and gives up silently if the worker cannot take a frame.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from app.services.execution.browser_client import BrowserClient
from browser_worker.protocol import FrameParams, FrameResult, WorkerError

START_AFTER_SECONDS = 1.0
INTERVAL_SECONDS = 1.0
MAX_FRAMES_PER_RUN = 120


class FrameBudget:
    def __init__(self, limit: int = MAX_FRAMES_PER_RUN) -> None:
        self.left = limit


class LiveFrames:
    def __init__(
        self,
        browser: BrowserClient,
        *,
        session_id: str,
        worker_id: str,
        budget: FrameBudget,
        on_frame: Callable[[FrameResult], Awaitable[None]],
    ) -> None:
        self._browser = browser
        self._params = FrameParams(session_id=session_id)
        self._worker_id = worker_id
        self._budget = budget
        self._on_frame = on_frame
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> LiveFrames:
        self._task = asyncio.create_task(self._run())
        return self

    async def __aexit__(self, *_: object) -> None:
        self._stop.set()
        if self._task is not None:
            with contextlib.suppress(Exception):
                await self._task

    async def _wait(self, seconds: float) -> bool:
        """True when stopped during the wait."""
        try:
            await asyncio.wait_for(self._stop.wait(), seconds)
        except TimeoutError:
            return False
        return True

    async def _run(self) -> None:
        if await self._wait(START_AFTER_SECONDS):
            return
        while self._budget.left > 0 and not self._stop.is_set():
            try:
                result = await self._browser.frame(self._params, worker_id=self._worker_id)
            except WorkerError:
                return
            if self._stop.is_set():
                return
            if result.artifact is not None:
                self._budget.left -= 1
                await self._on_frame(result)
            if await self._wait(INTERVAL_SECONDS):
                return
