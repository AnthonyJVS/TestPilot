"""Starting, listing, inspecting and cancelling executions (API side). Owner-scoped throughout."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.exceptions import AppError, ConflictError, NotFoundError
from app.domain.plan_validation import host_allowed
from app.domain.test_plan import TestPlan
from app.infrastructure.database.base import utcnow
from app.infrastructure.database.models import (
    ExecutionArtifact,
    ExecutionEvent,
    ExecutionStep,
    NodeExecution,
    Project,
    ProjectEnvironment,
    TestCase,
    TestExecution,
    TestSuite,
    TestVersion,
    WorkflowExecution,
    WorkflowVersion,
)
from app.infrastructure.database.models.execution import TERMINAL_STATUSES
from app.schemas.execution import RunCreate
from app.services.audit_service import AuditService
from app.services.context import RequestContext
from app.services.execution.runtime import ExecutionRuntime
from app.services.execution.test_data import Variable, missing_variables, required_variables

STALE_GRACE = timedelta(minutes=2)
VIEWPORT = {"width": 1280, "height": 800}


class RunRejectedError(AppError):
    code = "run.invalid"
    http_status = 422


class TooManyRunsError(AppError):
    code = "run.limit"
    http_status = 429


class ExecutionService:
    def __init__(self, db: AsyncSession, runtime: ExecutionRuntime) -> None:
        self._db = db
        self._runtime = runtime
        self._settings = runtime.settings
        self._audit = AuditService(db)

    # ------------------------------------------------------------------ start
    async def start_test_run(
        self, owner_id: uuid.UUID, version_id: uuid.UUID, body: RunCreate, ctx: RequestContext
    ) -> WorkflowExecution:
        row = (
            await self._db.execute(
                select(TestVersion, TestCase, Project)
                .join(TestCase, TestVersion.test_case_id == TestCase.id)
                .join(TestSuite, TestCase.suite_id == TestSuite.id)
                .join(Project, TestSuite.project_id == Project.id)
                .where(TestVersion.id == version_id, Project.owner_id == owner_id)
            )
        ).one_or_none()
        if row is None:
            raise NotFoundError("Version not found.")
        version, case, project = row
        environment = await self._environment(project, body.environment_id)
        base_url = (environment.base_url or project.base_url).rstrip("/")
        host = urlsplit(base_url).hostname or ""
        if not host_allowed(host, project.allowed_domains):
            raise RunRejectedError(
                f"The environment URL host '{host}' is not in the project's allowed domains."
            )
        plan = TestPlan.model_validate(version.plan)
        variables = {
            v.name: Variable(v.name, "", v.is_secret) for v in environment.variables
        }  # names only: values are resolved by the orchestrator
        missing = missing_variables(plan, variables)
        if missing:
            raise RunRejectedError(
                f"Environment '{environment.name}' is missing {', '.join(missing)}. "
                "Add them in the project's Environments tab.",
                details={"missing": missing},
            )
        active = await self._db.scalar(
            select(func.count())
            .select_from(WorkflowExecution)
            .where(
                WorkflowExecution.owner_id == owner_id,
                WorkflowExecution.status.in_(("queued", "running")),
            )
        )
        if (active or 0) >= self._settings.max_active_runs_per_user:
            raise TooManyRunsError(
                f"You already have {active} runs in progress. Wait for one to finish."
            )

        uses_secrets = any(kind == "secret" for kind, _ in required_variables(plan))
        notes: list[str] = []
        trace, video = body.trace, body.video
        if uses_secrets and (trace or video):
            trace = video = False
            notes.append(
                "Trace and video are off for this run because it types secret values: traces "
                "and recordings would capture them. Screenshots mask those fields."
            )
        if not self._runtime.isolated:
            notes.append(
                "Development mode: the browser runs inside the API process without container "
                "isolation."
            )
        execution = WorkflowExecution(
            owner_id=owner_id,
            project_id=project.id,
            kind="test_run",
            status="queued",
            trigger="manual",
            snapshot={
                "template": "test_run",
                "engine": "m4",
                "browser": body.browser,
                "environment": environment.name,
                "base_url": base_url,
                "allowed_domains": list(project.allowed_domains),
                "capture": {"screenshots": body.screenshots, "trace": trace, "video": video},
                "viewport": VIEWPORT,
                "isolated": self._runtime.isolated,
                "uses_secrets": uses_secrets,
                "notes": notes,
            },
            created_at=utcnow(),
        )
        self._db.add(execution)
        await self._db.flush()
        test = TestExecution(
            execution_id=execution.id,
            test_case_id=case.id,
            test_version_id=version.id,
            environment_id=environment.id,
            test_name=case.name,
            version_number=version.version,
            environment_name=environment.name,
            base_url=base_url,
            browser=body.browser,
            status="queued",
            steps_total=len(plan.steps),
        )
        self._db.add(test)
        await self._db.flush()
        for index, step in enumerate(plan.steps):
            self._db.add(
                ExecutionStep(
                    test_execution_id=test.id,
                    index=index,
                    action=step.action,
                    description=step.description[:300],
                    status="pending",
                )
            )
        for seq, (type_, message) in enumerate(
            [
                ("execution.created", f"Run of {case.name} v{version.version} created"),
                ("execution.queued", "Waiting for a worker"),
            ],
            start=1,
        ):
            self._db.add(
                ExecutionEvent(
                    execution_id=execution.id,
                    seq=seq,
                    ts=utcnow(),
                    type=type_,
                    category="system",
                    level="info",
                    message=message,
                    data={},
                )
            )
        self._audit.record(
            "test.run.start",
            "success",
            ctx=ctx,
            user_id=owner_id,
            target_type="execution",
            target_id=str(execution.id),
            details={"test_case_id": str(case.id), "version": version.version},
        )
        await self._db.commit()
        try:
            await self._runtime.jobs.enqueue(execution.id)
        except Exception as exc:
            await self._fail_unqueued(execution.id)
            raise AppError(
                "The run could not be queued. Check that Redis and the worker are running.",
                code="run.queue_unavailable",
            ) from exc
        return await self.get(owner_id, execution.id)

    async def _environment(
        self, project: Project, environment_id: uuid.UUID | None
    ) -> ProjectEnvironment:
        query = select(ProjectEnvironment).options(selectinload(ProjectEnvironment.variables))
        if environment_id is None:
            query = query.where(
                ProjectEnvironment.project_id == project.id, ProjectEnvironment.is_default
            )
        else:
            query = query.where(
                ProjectEnvironment.id == environment_id,
                ProjectEnvironment.project_id == project.id,
            )
        environment = await self._db.scalar(query)
        if environment is None:
            raise RunRejectedError("Choose an environment of this project.")
        return environment

    async def _fail_unqueued(self, execution_id: uuid.UUID) -> None:
        await self._db.execute(
            update(WorkflowExecution)
            .where(WorkflowExecution.id == execution_id)
            .values(
                status="error",
                finished_at=utcnow(),
                error_code="run.queue_unavailable",
                error_message="The run could not be queued.",
            )
        )
        await self._db.execute(
            update(TestExecution)
            .where(TestExecution.execution_id == execution_id)
            .values(status="error")
        )
        await self._db.commit()

    # ------------------------------------------------------------------ read
    async def get(self, owner_id: uuid.UUID, execution_id: uuid.UUID) -> WorkflowExecution:
        execution = (
            await self._db.execute(
                select(WorkflowExecution)
                .options(
                    selectinload(WorkflowExecution.test_executions).selectinload(
                        TestExecution.steps
                    ),
                    selectinload(WorkflowExecution.artifacts),
                    selectinload(WorkflowExecution.node_executions),
                )
                .where(WorkflowExecution.id == execution_id, WorkflowExecution.owner_id == owner_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if execution is None:
            raise NotFoundError("Run not found.")
        if await self._expire_if_stale(execution):
            return await self.get(owner_id, execution_id)
        return execution

    async def list_runs(
        self,
        owner_id: uuid.UUID,
        *,
        project_id: uuid.UUID | None = None,
        test_case_id: uuid.UUID | None = None,
        limit: int = 50,
        workflow_id: uuid.UUID | None = None,
    ) -> list[tuple[WorkflowExecution, TestExecution | None, tuple[int, int]]]:
        query = (
            select(WorkflowExecution, TestExecution)
            .outerjoin(TestExecution, TestExecution.execution_id == WorkflowExecution.id)
            .where(WorkflowExecution.owner_id == owner_id)
            .order_by(WorkflowExecution.created_at.desc())
            .limit(limit)
        )
        if project_id is not None:
            query = query.where(WorkflowExecution.project_id == project_id)
        if test_case_id is not None:
            query = query.where(TestExecution.test_case_id == test_case_id)
        if workflow_id is not None:
            query = query.where(WorkflowExecution.workflow_id == workflow_id)
        rows = [(e, t) for e, t in (await self._db.execute(query)).all()]
        expired = False
        for execution, _ in rows:
            expired = await self._expire_if_stale(execution) or expired
        if expired:
            return await self.list_runs(
                owner_id,
                project_id=project_id,
                test_case_id=test_case_id,
                limit=limit,
                workflow_id=workflow_id,
            )
        counts: dict[uuid.UUID, tuple[int, int]] = {}
        workflow_ids = [e.id for e, t in rows if t is None]
        if workflow_ids:
            completed = func.sum(case((NodeExecution.status == "completed", 1), else_=0))
            for execution_id, total, done in (
                await self._db.execute(
                    select(NodeExecution.execution_id, func.count(), completed)
                    .where(NodeExecution.execution_id.in_(workflow_ids))
                    .group_by(NodeExecution.execution_id)
                )
            ).all():
                counts[execution_id] = (int(total), int(done or 0))
        return [(e, t, counts.get(e.id, (0, 0))) for e, t in rows]

    async def workflow_graph(self, execution: WorkflowExecution) -> dict[str, Any] | None:
        if execution.workflow_version_id is None:
            return None
        version = await self._db.get(WorkflowVersion, execution.workflow_version_id)
        return version.graph if version else None

    async def events(
        self, owner_id: uuid.UUID, execution_id: uuid.UUID, *, after_seq: int, limit: int
    ) -> Sequence[ExecutionEvent]:
        await self._owned(owner_id, execution_id)
        return await fetch_events(self._db, execution_id, after_seq=after_seq, limit=limit)

    async def artifact(
        self, owner_id: uuid.UUID, artifact_id: uuid.UUID
    ) -> tuple[ExecutionArtifact, Path]:
        artifact = await self._db.scalar(
            select(ExecutionArtifact)
            .join(WorkflowExecution)
            .where(ExecutionArtifact.id == artifact_id, WorkflowExecution.owner_id == owner_id)
        )
        if artifact is None:
            raise NotFoundError("Artifact not found.")
        root = self._runtime.artifacts_root
        path = (root / artifact.storage_path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise NotFoundError("The artifact file is no longer available.")
        return artifact, path

    async def _owned(self, owner_id: uuid.UUID, execution_id: uuid.UUID) -> WorkflowExecution:
        execution = await self._db.scalar(
            select(WorkflowExecution).where(
                WorkflowExecution.id == execution_id, WorkflowExecution.owner_id == owner_id
            )
        )
        if execution is None:
            raise NotFoundError("Run not found.")
        return execution

    # ------------------------------------------------------------------ cancel
    async def cancel(
        self, owner_id: uuid.UUID, execution_id: uuid.UUID, ctx: RequestContext
    ) -> WorkflowExecution:
        execution = await self._owned(owner_id, execution_id)
        if execution.status in TERMINAL_STATUSES:
            raise ConflictError("This run has already finished.", code="run.finished")
        now = utcnow()
        # A queued run is cancelled here directly; a running one is stopped by its orchestrator.
        cancelled = await self._db.execute(
            update(WorkflowExecution)
            .where(WorkflowExecution.id == execution_id, WorkflowExecution.status == "queued")
            .values(status="cancelled", cancel_requested_at=now, finished_at=now)
        )
        if cancelled.rowcount:  # type: ignore[attr-defined]
            await self._db.execute(
                update(TestExecution)
                .where(TestExecution.execution_id == execution_id)
                .values(status="cancelled", finished_at=now)
            )
            await self._db.execute(
                update(ExecutionStep)
                .where(
                    ExecutionStep.test_execution_id.in_(
                        select(TestExecution.id).where(TestExecution.execution_id == execution_id)
                    )
                )
                .values(status="skipped")
            )
            last = await self._db.scalar(
                select(func.max(ExecutionEvent.seq)).where(
                    ExecutionEvent.execution_id == execution_id
                )
            )
            self._db.add(
                ExecutionEvent(
                    execution_id=execution_id,
                    seq=(last or 0) + 1,
                    ts=now,
                    type="execution.cancelled",
                    category="system",
                    level="warning",
                    message="Run cancelled before it started",
                    data={"status": "cancelled"},
                )
            )
        else:
            await self._db.execute(
                update(WorkflowExecution)
                .where(WorkflowExecution.id == execution_id)
                .values(cancel_requested_at=now)
            )
        self._audit.record(
            "test.run.cancel",
            "success",
            ctx=ctx,
            user_id=owner_id,
            target_type="execution",
            target_id=str(execution_id),
        )
        await self._db.commit()
        await self._runtime.notifier.publish(execution_id)
        return await self.get(owner_id, execution_id)

    # ------------------------------------------------------------------ stale runs
    async def _expire_if_stale(self, execution: WorkflowExecution) -> bool:
        """A run far past its time limit lost its worker; report it instead of spinning."""
        if execution.status not in ("queued", "running"):
            return False
        reference = execution.started_at or execution.created_at
        limit = timedelta(seconds=self._settings.run_max_seconds) + STALE_GRACE
        if execution.status == "queued":
            limit = timedelta(hours=1)
        if utcnow() - reference < limit:
            return False
        now = utcnow()
        result = await self._db.execute(
            update(WorkflowExecution)
            .where(
                WorkflowExecution.id == execution.id,
                WorkflowExecution.status == execution.status,
            )
            .values(
                status="error",
                finished_at=now,
                error_code="run.interrupted",
                error_message="The run stopped responding (worker lost).",
            )
        )
        if result.rowcount:  # type: ignore[attr-defined]
            await self._db.execute(
                update(TestExecution)
                .where(TestExecution.execution_id == execution.id)
                .values(status="error", finished_at=now)
            )
        await self._db.commit()
        return True


async def fetch_events(
    db: AsyncSession, execution_id: uuid.UUID, *, after_seq: int, limit: int
) -> Sequence[ExecutionEvent]:
    result = await db.execute(
        select(ExecutionEvent)
        .where(ExecutionEvent.execution_id == execution_id, ExecutionEvent.seq > after_seq)
        .order_by(ExecutionEvent.seq)
        .limit(limit)
    )
    return result.scalars().all()
