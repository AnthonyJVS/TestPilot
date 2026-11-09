"""``python -m browser_worker`` — run the isolated browser worker against Redis.

Configuration (environment variables only; the worker receives no other secrets):

* ``BROWSER_WORKER_REDIS_URL`` — Redis used for the command queues (required).
* ``ARTIFACTS_DIR`` — where screenshots, traces and logs are written (default ``/artifacts``).
* ``BROWSER_MAX_SESSIONS`` — concurrent browser sessions (default 2).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from redis.asyncio import Redis

from browser_worker.engine import BrowserEngine
from browser_worker.server import RedisWorkerServer


async def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
    )
    redis_url = os.environ.get("BROWSER_WORKER_REDIS_URL")
    if not redis_url:
        sys.exit("BROWSER_WORKER_REDIS_URL is required")
    engine = BrowserEngine(
        Path(os.environ.get("ARTIFACTS_DIR", "/artifacts")),
        max_sessions=int(os.environ.get("BROWSER_MAX_SESSIONS", "2")),
    )
    await engine.start()
    redis = Redis.from_url(redis_url, decode_responses=True)
    server = RedisWorkerServer(redis, engine)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, server.stop)
        except NotImplementedError:  # Windows
            pass
    try:
        await server.serve()
    finally:
        await engine.stop()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
