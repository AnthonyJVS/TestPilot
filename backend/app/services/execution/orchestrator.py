"""Runs one ``test_run`` execution: the built-in workflow template of ADR-010.

    launch_browser → execute_test (one node, one event per step) → collect_artifacts

The orchestrator is the only component that sees decrypted test data. It claims the execution
atomically (``queued`` → ``running``), so a job delivered twice runs once, and it is the only
event writer while it owns the run.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.crypto import EncryptedSecret, SecretCipher
from app.domain.test_plan import TestPlan
from app.infrastructure.database.base import utcnow
from app.infrastructure.database.models import (
    ExecutionArtifact,
    ExecutionEvent,
    ExecutionStep,
    ProjectEnvironment,
    TestExecution,
    TestVersion,
    WorkflowExecution,
)
from app.services.execution.browser_client import BrowserClient
from app.services.execution.events import EventNotifier, EventRecorder
from app.services.execution.live_frames import FrameBudget, LiveFrames
from app.services.execution.test_data import (
    MissingVariablesError,
    SecretScrubber,
    Variable,
    build_commands,
)
from app.services.project_service import secret_aad
from browser_worker.protocol import (
    ArtifactInfo,
    CaptureOptions,
    CloseSessionParams,
    FrameResult,
    OpenSessionParams,
    OpenSessionResult,
    StepParams,
    StepResult,
    Viewport,
    WorkerError,
)

logger = logging.getLogger(__name__)

NODE_LAUNCH = "launch_browser"
NODE_TEST = "execute_test"
NODE_ARTIFACTS = "collect_artifacts"

# Worker errors that mean the infrastructure failed, not the application under test.
INFRASTRUCTURE_ERRORS = frozenset(
    {
        "browser.unavailable",
        "browser.launch_failed",
        "session.not_found",
        "worker.busy",
        "worker.timeout",
        "request.invalid",
        "internal",
    }
)
MAX_DETAIL_EVENTS = 150  # console / network / blocked events per run
CANCEL_POLL_SECONDS = 1.0


class _Cancelled(Exception):
    pass


@dataclass
class _Outcome:
    status: str = "passed"
    code: str | None = None
    message: str | None = None

    def fail(self, status: str, code: str, message: str) -> None:
        self.status, self.code, self.message = status, code, message


@dataclass
class _Session:
    opened: OpenSessionResult
    open: bool = True
    frames: FrameBudget = field(default_factory=FrameBudget)


class TestRunOrchestrator:
    __test__ = False

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        cipher: SecretCipher,
        browser: BrowserClient,
        notifier: EventNotifier,
    ) -> None:
        self._sf = session_factory
        self._settings = settings
        self._cipher = cipher
        self._browser = browser
        self._notifier = notifier

    async def execute(self, execution_id: uuid.UUID) -> None:
        async with self._sf() as db:
            claimed = await db.execute(
                update(WorkflowExecution)
                .where(WorkflowExecution.id == execution_id, WorkflowExecution.status == "queued")
                .values(status="running", started_at=utcnow())
            )
            await db.commit()
            if claimed.rowcount == 0:  # type: ignore[attr-defined]
                logger.info("Execution %s was not queued; skipping", execution_id)
                return
            execution = (
                await db.execute(
                    select(WorkflowExecution)
                    .options(
                        selectinload(WorkflowExecution.test_executions).selectinload(
                            TestExecution.steps
                        )
                    )
                    .where(WorkflowExecution.id == execution_id)
                )
            ).scalar_one()
            last_seq = await db.scalar(
                select(func.max(ExecutionEvent.seq)).where(
                    ExecutionEvent.execution_id == execution_id
                )
            )
            recorder = EventRecorder(db, self._notifier, execution_id, last_seq or 0)
            test = execution.test_executions[0]
            outcome = _Outcome()
            try:
                await self._run(db, recorder, execution, test, outcome)
            except Exception:
                logger.exception("Execution %s crashed", execution_id)
                await db.rollback()
                await db.refresh(execution)
                test = (
                    await db.execute(
                        select(TestExecution)
                        .options(selectinload(TestExecution.steps))
                        .where(TestExecution.id == test.id)
                        .execution_options(populate_existing=True)
                    )
                ).scalar_one()
                outcome.fail("error", "internal", "The run stopped because of an internal error.")
            await self._finish(db, recorder, execution, test, outcome)

    # ------------------------------------------------------------------ run
    async def _run(
        self,
        db: AsyncSession,
        rec: EventRecorder,
        execution: WorkflowExecution,
        test: TestExecution,
        outcome: _Outcome,
    ) -> None:
        started = time.monotonic()
        test.status, test.started_at = "running", utcnow()
        snapshot = execution.snapshot
        await rec.emit(
            "execution.started",
            f"Run started: {test.test_name} v{test.version_number} on {test.browser}",
        )
        version = await db.get(TestVersion, test.test_version_id) if test.test_version_id else None
        environment = (
            await db.scalar(
                select(ProjectEnvironment)
                .options(selectinload(ProjectEnvironment.variables))
                .where(ProjectEnvironment.id == test.environment_id)
            )
            if test.environment_id
            else None
        )
        if version is None or environment is None:
            outcome.fail("error", "run.stale", "The test version or environment was deleted.")
            return
        variables = self._variables(environment)
        scrubber = SecretScrubber(variables)
        try:
            commands = build_commands(TestPlan.model_validate(version.plan), variables)
        except MissingVariablesError as exc:
            outcome.fail(
                "error",
                "run.missing_variables",
                f"Environment '{test.environment_name}' is missing {', '.join(exc.names)}.",
            )
            return
        for note in snapshot.get("notes", []):
            rec.add("execution.notice", note, level="warning")

        # launch_browser
        rec.add("node.started", f"Launching {test.browser}", category="node", node_id=NODE_LAUNCH)
        await rec.flush()
        capture = snapshot["capture"]
        try:
            opened = await self._browser.open(
                OpenSessionParams(
                    execution_id=execution.id,
                    browser=test.browser,
                    base_url=test.base_url,
                    allowed_domains=snapshot["allowed_domains"],
                    allow_private_network=self._settings.browser_allow_private_network,
                    viewport=Viewport(**snapshot["viewport"]),
                    capture=CaptureOptions(**capture),
                )
            )
        except WorkerError as exc:
            message = scrubber.text(exc.message)
            await rec.emit(
                "node.failed",
                message,
                category="node",
                level="error",
                node_id=NODE_LAUNCH,
                data={"code": exc.code},
            )
            outcome.fail("error", exc.code, message)
            return
        session = _Session(opened)
        test.browser_version = opened.browser_version
        rec.add(
            "browser.worker.started",
            f"{test.browser} {opened.browser_version} ready",
            category="browser",
            node_id=NODE_LAUNCH,
            data={"browser_version": opened.browser_version, "worker_id": opened.worker_id},
        )
        rec.add("node.completed", "Browser ready", category="node", node_id=NODE_LAUNCH)
        rec.add(
            "node.started",
            f"Executing {len(commands)} steps",
            category="node",
            node_id=NODE_TEST,
        )
        await rec.flush()

        details = 0
        try:
            for row, command in zip(test.steps, commands, strict=True):
                if await self._cancel_requested(execution.id):
                    raise _Cancelled
                if time.monotonic() - started > self._settings.run_max_seconds:
                    outcome.fail(
                        "error",
                        "run.timeout",
                        f"The run exceeded {self._settings.run_max_seconds} seconds.",
                    )
                    break
                row.status, row.started_at = "running", utcnow()
                await rec.emit(
                    "browser.step.started",
                    f"Step {row.index + 1}: {row.description}",
                    category="browser",
                    node_id=NODE_TEST,
                    step_index=row.index,
                    data={"action": row.action},
                )
                params = StepParams(
                    session_id=opened.session_id,
                    index=row.index,
                    step=command.step,
                    sensitive=command.sensitive,
                    screenshot_name=command.screenshot_name,
                )
                result = await self._step(db, rec, execution, test, session, params)
                result = StepResult.model_validate(scrubber.data(result.model_dump()))
                details = await self._record_step(db, rec, execution, test, row, result, details)
                if result.status == "failed":
                    error = result.error
                    code = error.code if error else "step.error"
                    status = "error" if code in INFRASTRUCTURE_ERRORS else "failed"
                    outcome.fail(
                        status,
                        code,
                        f"Step {row.index + 1} failed: {error.message if error else 'error'}",
                    )
                    break
        except _Cancelled:
            outcome.fail("cancelled", "run.cancelled", "The run was cancelled.")
        except WorkerError as exc:
            outcome.fail("error", exc.code, scrubber.text(exc.message))
        finally:
            self._settle_steps(test)
            test_ok = outcome.status == "passed"
            rec.add(
                "node.completed" if test_ok else "node.failed",
                f"{test.steps_passed}/{test.steps_total} steps passed",
                category="node",
                level="info" if test_ok else "error",
                node_id=NODE_TEST,
            )
            await rec.flush()
            await self._collect(db, rec, execution, test, session, scrubber)

    async def _step(
        self,
        db: AsyncSession,
        rec: EventRecorder,
        execution: WorkflowExecution,
        test: TestExecution,
        session: _Session,
        params: StepParams,
    ) -> StepResult:
        limits = [params.step.timeout_ms or 0, 30_000]
        timeout = max(limits) / 1000 + 30
        step_task = asyncio.create_task(
            self._browser.step(params, worker_id=session.opened.worker_id, wait_seconds=timeout)
        )
        cancel_task = asyncio.create_task(self._wait_for_cancel(execution.id))

        async def on_frame(frame: FrameResult) -> None:
            await self._record_frame(db, rec, execution, test, frame)

        try:
            async with LiveFrames(
                self._browser,
                session_id=session.opened.session_id,
                worker_id=session.opened.worker_id,
                budget=session.frames,
                on_frame=on_frame,
            ):
                done, _ = await asyncio.wait(
                    {step_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
                )
        finally:
            cancel_task.cancel()
        if step_task in done:
            return step_task.result()
        # Cancelled mid-step: closing the session aborts the in-flight browser action.
        await self._close_session(session)
        with contextlib.suppress(Exception):
            await step_task
        raise _Cancelled

    async def _record_frame(
        self,
        db: AsyncSession,
        rec: EventRecorder,
        execution: WorkflowExecution,
        test: TestExecution,
        frame: FrameResult,
    ) -> None:
        assert frame.artifact is not None
        artifact = self._artifact(execution, test, frame.artifact)
        if artifact is None:
            return
        db.add(artifact)
        await db.flush()
        rec.add(
            "browser.frame",
            "Live frame",
            category="browser",
            node_id=NODE_TEST,
            step_index=frame.step_index,
            data={
                "artifact_id": str(artifact.id),
                "kind": "frame",
                "interim": True,
                "url": frame.url,
                "content_type": "image/jpeg",
            },
        )
        await rec.flush()

    async def _wait_for_cancel(self, execution_id: uuid.UUID) -> None:
        # Polls the database: the cancel request may come from another process.
        while not await self._cancel_requested(execution_id):  # noqa: ASYNC110
            await asyncio.sleep(CANCEL_POLL_SECONDS)

    async def _cancel_requested(self, execution_id: uuid.UUID) -> bool:
        async with self._sf() as db:
            requested = await db.scalar(
                select(WorkflowExecution.cancel_requested_at).where(
                    WorkflowExecution.id == execution_id
                )
            )
        return requested is not None

    async def _close_session(self, session: _Session) -> list[ArtifactInfo]:
        if not session.open:
            return []
        session.open = False
        try:
            result = await self._browser.close(
                CloseSessionParams(session_id=session.opened.session_id),
                worker_id=session.opened.worker_id,
            )
        except WorkerError:
            logger.warning("Could not close browser session", exc_info=True)
            return []
        return list(result.artifacts)

    # ------------------------------------------------------------------ recording
    async def _record_step(
        self,
        db: AsyncSession,
        rec: EventRecorder,
        execution: WorkflowExecution,
        test: TestExecution,
        row: ExecutionStep,
        result: StepResult,
        details: int,
    ) -> int:
        row.status = result.status
        row.finished_at = utcnow()
        row.duration_ms = result.duration_ms
        row.url = result.url
        row.page_snapshot = result.page_snapshot
        if result.error:
            row.error_code, row.error_message = result.error.code, result.error.message
            test.steps_failed += 1
        else:
            test.steps_passed += 1
        for entry in result.blocked:
            if details < MAX_DETAIL_EVENTS:
                details += 1
                rec.add(
                    "browser.request.blocked",
                    f"Blocked {entry.url}: {entry.reason}",
                    category="browser",
                    level="warning",
                    node_id=NODE_TEST,
                    step_index=row.index,
                    data=entry.model_dump(),
                )
        for console in result.console:
            if details < MAX_DETAIL_EVENTS:
                details += 1
                serious = console.level in ("error", "pageerror")
                rec.add(
                    "browser.console",
                    f"[{console.level}] {console.text}",
                    category="browser",
                    level="warning" if serious else "info",
                    node_id=NODE_TEST,
                    step_index=row.index,
                    data=console.model_dump(),
                )
        for request in result.network_failures:
            if details < MAX_DETAIL_EVENTS:
                details += 1
                outcome = request.status or request.failure
                rec.add(
                    "browser.network.failed",
                    f"{request.method} {request.url} → {outcome}",
                    category="browser",
                    level="warning",
                    node_id=NODE_TEST,
                    step_index=row.index,
                    data=request.model_dump(),
                )
        for info in result.artifacts:
            artifact = self._artifact(execution, test, info)
            if artifact is None:
                continue
            db.add(artifact)
            await db.flush()
            rec.add(
                "browser.frame" if info.content_type == "image/jpeg" else "artifact.created",
                f"Screenshot after step {row.index + 1}"
                if info.content_type == "image/jpeg"
                else f"Screenshot {info.name}",
                category="browser",
                node_id=NODE_TEST,
                step_index=row.index,
                data={
                    "artifact_id": str(artifact.id),
                    "kind": info.kind,
                    "url": result.url,
                    "content_type": info.content_type,
                },
            )
        passed = result.status == "passed"
        rec.add(
            "browser.step.passed" if passed else "browser.step.failed",
            f"Step {row.index + 1} {'passed' if passed else 'failed'} in {result.duration_ms} ms"
            + ("" if passed or not result.error else f": {result.error.message}"),
            category="browser",
            level="info" if passed else "error",
            node_id=NODE_TEST,
            step_index=row.index,
            data={
                "action": row.action,
                "duration_ms": result.duration_ms,
                "url": result.url,
                "title": result.title,
                "error_code": result.error.code if result.error else None,
            },
        )
        await rec.flush()
        return details

    def _artifact(
        self, execution: WorkflowExecution, test: TestExecution, info: ArtifactInfo
    ) -> ExecutionArtifact | None:
        path = PurePosixPath(info.path)
        if path.is_absolute() or ".." in path.parts or path.parts[:1] != (str(execution.id),):
            logger.warning("Ignoring artifact with unexpected path %s", info.path)
            return None
        return ExecutionArtifact(
            execution_id=execution.id,
            test_execution_id=test.id,
            step_index=info.step_index,
            kind=info.kind,
            name=info.name,
            content_type=info.content_type,
            size_bytes=info.size_bytes,
            sha256=info.sha256,
            storage_path=path.as_posix(),
        )

    async def _collect(
        self,
        db: AsyncSession,
        rec: EventRecorder,
        execution: WorkflowExecution,
        test: TestExecution,
        session: _Session,
        scrubber: SecretScrubber,
    ) -> None:
        rec.add("node.started", "Collecting artifacts", category="node", node_id=NODE_ARTIFACTS)
        await rec.flush()
        artifacts = await self._close_session(session)
        for info in artifacts:
            artifact = self._artifact(execution, test, info)
            if artifact is None:
                continue
            db.add(artifact)
            await db.flush()
            rec.add(
                "artifact.created",
                f"{info.kind.replace('_', ' ').capitalize()} saved ({info.size_bytes} bytes)",
                category="browser",
                node_id=NODE_ARTIFACTS,
                data={"artifact_id": str(artifact.id), "kind": info.kind, "name": info.name},
            )
        rec.add(
            "node.completed",
            f"{len(artifacts)} artifacts saved",
            category="node",
            node_id=NODE_ARTIFACTS,
        )
        await rec.flush()

    async def _finish(
        self,
        db: AsyncSession,
        rec: EventRecorder,
        execution: WorkflowExecution,
        test: TestExecution,
        outcome: _Outcome,
    ) -> None:
        now = utcnow()
        self._settle_steps(test)
        for row in (execution, test):
            row.status = outcome.status
            row.finished_at = now
            if row.started_at is not None:
                row.duration_ms = int((now - row.started_at).total_seconds() * 1000)
        execution.error_code = outcome.code
        execution.error_message = outcome.message
        summary = f"{test.steps_passed}/{test.steps_total} steps passed"
        if outcome.status == "passed":
            rec.add("execution.completed", f"Run passed: {summary}", data={"status": "passed"})
        elif outcome.status == "cancelled":
            rec.add(
                "execution.cancelled",
                "Run cancelled",
                level="warning",
                data={"status": "cancelled"},
            )
        else:
            rec.add(
                "execution.failed",
                outcome.message or "Run failed",
                level="error",
                data={"status": outcome.status, "code": outcome.code, "summary": summary},
            )
        await rec.flush()

    @staticmethod
    def _settle_steps(test: TestExecution) -> None:
        for row in test.steps:
            if row.status == "pending":
                row.status = "skipped"
            elif row.status == "running":
                row.status, row.finished_at = "failed", utcnow()

    def _variables(self, environment: ProjectEnvironment) -> dict[str, Variable]:
        variables: dict[str, Variable] = {}
        for item in environment.variables:
            if item.is_secret:
                if item.ciphertext is None or item.nonce is None or item.key_id is None:
                    continue
                value = self._cipher.decrypt(
                    EncryptedSecret(item.ciphertext, item.nonce, item.key_id),
                    associated_data=secret_aad(environment.id, item.name),
                )
            else:
                value = item.value or ""
            variables[item.name] = Variable(item.name, value, item.is_secret)
        return variables
