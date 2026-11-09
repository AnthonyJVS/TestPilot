"""Runtime services shared by the nodes of one workflow execution.

Nodes run concurrently, so every database write and event goes through this context under a
lock (one SQLAlchemy session must never be used by two tasks at once). Browser sessions are
held here, keyed by an opaque reference that flows along ``session`` edges; actions on the
same session are serialised by a per-session lock.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.crypto import SecretCipher
from app.domain.test_plan import Step
from app.infrastructure.database.base import utcnow
from app.infrastructure.database.models import ExecutionArtifact, NodeExecution, WorkflowExecution
from app.services.ai.client_factory import ProviderClientFactory
from app.services.ai.orchestrator import AIOrchestrator
from app.services.ai.registry import ProviderRegistry
from app.services.ai.router import TaskRouter
from app.services.execution.browser_client import BrowserClient
from app.services.execution.events import EventRecorder
from app.services.execution.test_data import (
    MissingVariablesError,
    SecretScrubber,
    Variable,
    command_for,
)
from app.services.workflows.registry import NodeError
from browser_worker.protocol import (
    ArtifactInfo,
    BlockedRequest,
    CaptureOptions,
    CloseSessionParams,
    ConsoleEntry,
    NetworkEntry,
    OpenSessionParams,
    OpenSessionResult,
    StepParams,
    StepResult,
    Viewport,
    WorkerError,
)

logger = logging.getLogger(__name__)

TRANSIENT_WORKER_ERRORS = frozenset({"worker.timeout", "worker.busy"})
MAX_DETAIL_EVENTS = 200


@dataclass
class Environment:
    id: uuid.UUID
    name: str
    base_url: str
    variables: dict[str, Variable]


@dataclass
class SessionState:
    ref: str
    node_id: str
    opened: OpenSessionResult
    environment: Environment
    browser: str
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    console: list[ConsoleEntry] = field(default_factory=list)
    network_failures: list[NetworkEntry] = field(default_factory=list)
    blocked: list[BlockedRequest] = field(default_factory=list)
    url: str | None = None
    open: bool = True

    def handle(self) -> dict[str, Any]:
        """The value carried by ``session`` edges (no secrets, no internals)."""
        return {
            "session": self.ref,
            "browser": self.browser,
            "environment": self.environment.name,
            "url": self.url,
        }


class RunContext:
    def __init__(
        self,
        *,
        db: AsyncSession,
        recorder: EventRecorder,
        execution: WorkflowExecution,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        cipher: SecretCipher,
        providers: ProviderRegistry,
        browser: BrowserClient,
        allowed_domains: list[str],
        environments: dict[str, Environment],
        uses_secrets: bool,
    ) -> None:
        self._db = db
        self._lock = asyncio.Lock()
        self.recorder = recorder
        self.execution = execution
        self.settings = settings
        self.session_factory = session_factory
        self.cipher = cipher
        self.providers = providers
        self.browser = browser
        self.allowed_domains = allowed_domains
        self.environments = environments
        self.uses_secrets = uses_secrets
        self.sessions: dict[str, SessionState] = {}
        self._step_counter = 0
        self._details = 0
        all_variables: dict[str, Variable] = {}
        for env in environments.values():
            for name, variable in env.variables.items():
                all_variables[f"{env.name}:{name}"] = variable
        self.scrubber = SecretScrubber(all_variables)

    @property
    def owner_id(self) -> uuid.UUID:
        return self.execution.owner_id

    # ------------------------------------------------------------------ persistence
    async def emit(self, type_: str, message: str, **kwargs: Any) -> None:
        async with self._lock:
            self.recorder.add(type_, self.scrubber.text(message), **kwargs)
            await self.recorder.flush()

    async def update_node(self, row: NodeExecution, **values: Any) -> None:
        async with self._lock:
            for key, value in values.items():
                setattr(row, key, value)
            await self._db.commit()

    async def add_artifact(
        self, info: ArtifactInfo, *, node_id: str, url: str | None = None
    ) -> None:
        path = PurePosixPath(info.path)
        if path.is_absolute() or ".." in path.parts or path.parts[:1] != (str(self.execution.id),):
            logger.warning("Ignoring artifact with unexpected path %s", info.path)
            return
        async with self._lock:
            artifact = ExecutionArtifact(
                execution_id=self.execution.id,
                node_id=node_id,
                step_index=info.step_index,
                kind=info.kind,
                name=info.name,
                content_type=info.content_type,
                size_bytes=info.size_bytes,
                sha256=info.sha256,
                storage_path=path.as_posix(),
                created_at=utcnow(),
            )
            self._db.add(artifact)
            await self._db.flush()
            frame = info.content_type == "image/jpeg"
            self.recorder.add(
                "browser.frame" if frame else "artifact.created",
                f"Screenshot after {node_id}" if frame else f"{info.kind} saved: {info.name}",
                category="browser",
                node_id=node_id,
                step_index=info.step_index,
                data={
                    "artifact_id": str(artifact.id),
                    "kind": info.kind,
                    "url": url,
                    "content_type": info.content_type,
                },
            )
            await self.recorder.flush()

    # ------------------------------------------------------------------ browser
    async def open_session(
        self, node_id: str, *, browser: str, environment: str, capture: CaptureOptions
    ) -> SessionState:
        env = self.environments.get(environment)
        if env is None:
            raise NodeError("node.environment_missing", f"Environment '{environment}' not found.")
        if self.uses_secrets and (capture.trace or capture.video):
            capture = capture.model_copy(update={"trace": False, "video": False})
        ref = f"s{len(self.sessions) + 1}"
        try:
            opened = await self.browser.open(
                OpenSessionParams(
                    execution_id=self.execution.id,
                    browser=browser,
                    base_url=env.base_url,
                    allowed_domains=self.allowed_domains,
                    allow_private_network=self.settings.browser_allow_private_network,
                    viewport=Viewport(),
                    capture=capture,
                    label=ref,
                )
            )
        except WorkerError as exc:
            raise NodeError(
                exc.code, exc.message, transient=exc.code in TRANSIENT_WORKER_ERRORS
            ) from exc
        state = SessionState(ref, node_id, opened, env, browser)
        self.sessions[ref] = state
        return state

    def session(self, handle: Any) -> SessionState:
        ref = handle.get("session") if isinstance(handle, dict) else None
        state = self.sessions.get(ref) if isinstance(ref, str) else None
        if state is None or not state.open:
            raise NodeError("node.session_missing", "The browser session is not available.")
        return state

    async def run_step(
        self, node_id: str, state: SessionState, step: Step, *, label: str | None = None
    ) -> StepResult:
        """Run one DSL step on a session, record its evidence; raise NodeError if it fails."""
        try:
            command = command_for(step, state.environment.variables)
        except MissingVariablesError as exc:
            raise NodeError(
                "node.missing_variables",
                f"Environment '{state.environment.name}' is missing {', '.join(exc.names)}.",
            ) from exc
        async with state.lock:
            self._step_counter += 1
            index = self._step_counter
            params = StepParams(
                session_id=state.opened.session_id,
                index=min(index, 999),
                step=command.step,
                sensitive=command.sensitive,
                screenshot_name=command.screenshot_name,
            )
            wait = max(step.timeout_ms or 0, 30_000) / 1000 + 30
            try:
                raw = await self.browser.step(
                    params, worker_id=state.opened.worker_id, wait_seconds=wait
                )
            except WorkerError as exc:
                raise NodeError(
                    exc.code, exc.message, transient=exc.code in TRANSIENT_WORKER_ERRORS
                ) from exc
        result = StepResult.model_validate(self.scrubber.data(raw.model_dump()))
        state.url = result.url
        state.console.extend(result.console)
        state.network_failures.extend(result.network_failures)
        state.blocked.extend(result.blocked)
        await self._record_evidence(node_id, result)
        for info in result.artifacts:
            await self.add_artifact(info, node_id=node_id, url=result.url)
        passed = result.status == "passed"
        what = label or step.description
        await self.emit(
            "browser.step.passed" if passed else "browser.step.failed",
            f"{what}: {'passed' if passed else 'failed'} in {result.duration_ms} ms"
            + ("" if passed or not result.error else f" — {result.error.message}"),
            category="browser",
            level="info" if passed else "error",
            node_id=node_id,
            step_index=result.index,
            data={
                "action": step.action,
                "duration_ms": result.duration_ms,
                "url": result.url,
                "error_code": result.error.code if result.error else None,
            },
        )
        if not passed:
            error = result.error
            raise NodeError(
                error.code if error else "step.error",
                error.message if error else "The step failed.",
                transient=bool(error and error.code in TRANSIENT_WORKER_ERRORS),
            )
        return result

    async def _record_evidence(self, node_id: str, result: StepResult) -> None:
        entries: list[tuple[str, str, str, dict[str, Any]]] = []
        for blocked in result.blocked:
            entries.append(
                (
                    "browser.request.blocked",
                    f"Blocked {blocked.url}: {blocked.reason}",
                    "warning",
                    blocked.model_dump(),
                )
            )
        for console in result.console:
            serious = console.level in ("error", "pageerror")
            entries.append(
                (
                    "browser.console",
                    f"[{console.level}] {console.text}",
                    "warning" if serious else "info",
                    console.model_dump(),
                )
            )
        for request in result.network_failures:
            entries.append(
                (
                    "browser.network.failed",
                    f"{request.method} {request.url} → {request.status or request.failure}",
                    "warning",
                    request.model_dump(),
                )
            )
        if not entries:
            return
        async with self._lock:
            for type_, message, level, data in entries:
                if self._details >= MAX_DETAIL_EVENTS:
                    break
                self._details += 1
                self.recorder.add(
                    type_,
                    message,
                    category="browser",
                    level=level,
                    node_id=node_id,
                    step_index=result.index,
                    data=data,
                )
            await self.recorder.flush()

    async def close_sessions(self) -> None:
        for state in list(self.sessions.values()):
            if not state.open:
                continue
            state.open = False
            try:
                closed = await self.browser.close(
                    CloseSessionParams(session_id=state.opened.session_id),
                    worker_id=state.opened.worker_id,
                )
            except WorkerError:
                logger.warning("Could not close browser session", exc_info=True)
                continue
            for info in closed.artifacts:
                await self.add_artifact(info, node_id=state.node_id)

    # ------------------------------------------------------------------ AI
    def ai(self, db: AsyncSession) -> AIOrchestrator:
        return AIOrchestrator(
            db,
            self.settings,
            TaskRouter(db, self.providers),
            ProviderClientFactory(self.settings, self.providers, self.cipher),
        )
