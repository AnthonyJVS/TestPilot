"""Isolated browser worker (ADR-005).

Executes validated test-plan steps in Playwright. It deliberately has no database access, no AI
provider keys and no dependency on the ``app`` package: it receives fully resolved commands,
enforces its own network policy and writes artifacts to a dedicated directory.

Two hosts run the same engine:

* ``python -m browser_worker`` — a standalone process (the Docker ``browser-worker`` service)
  serving commands from Redis.
* ``app.services.execution.browser_client.ThreadedBrowserClient`` — development only: the engine
  runs on a dedicated thread inside the API process when no Redis/Docker is available.
"""

PROTOCOL_VERSION = 1
