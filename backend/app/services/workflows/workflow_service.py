"""Workflows: create from templates, save immutable versions, validate, duplicate and run."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.exceptions import AppError, ConflictError, NotFoundError
from app.domain.workflow import GraphIssue, WorkflowGraph
from app.infrastructure.database.base import utcnow
from app.infrastructure.database.models import (
    ExecutionEvent,
    NodeExecution,
    Project,
    ProjectEnvironment,
    TestCase,
    TestSuite,
    TestVersion,
    Workflow,
    WorkflowExecution,
    WorkflowVersion,
)
from app.schemas.workflow import NodeTypeOut, PortOut, WorkflowCreate, WorkflowUpdate
from app.services.audit_service import AuditService
from app.services.context import RequestContext
from app.services.execution.execution_service import RunQueueUnavailableError, TooManyRunsError
from app.services.execution.runtime import ExecutionRuntime
from app.services.workflows import templates
from app.services.workflows.catalog import node_registry
from app.services.workflows.registry import NodeType, ValidationContext
from app.services.workflows.validation import has_errors, validate_graph

logger = logging.getLogger(__name__)


class WorkflowRejectedError(AppError):
    code = "workflow.invalid"
    http_status = 422


def describe(node_type: NodeType) -> NodeTypeOut:
    def ports(items: Sequence[object]) -> list[PortOut]:
        return [
            PortOut(
                name=p.name,  # type: ignore[attr-defined]
                type=p.type,  # type: ignore[attr-defined]
                label=p.label,  # type: ignore[attr-defined]
                required=p.required,  # type: ignore[attr-defined]
                multi=p.multi,  # type: ignore[attr-defined]
            )
            for p in items
        ]

    model = node_type.config_model
    return NodeTypeOut(
        type=node_type.type_id,
        version=node_type.version,
        category=node_type.category,
        label=node_type.label,
        description=node_type.description,
        available=node_type.available,
        milestone=node_type.milestone,
        entry=node_type.entry or not any(p.required for p in node_type.inputs),
        inputs=ports(node_type.inputs),
        outputs=ports(node_type.all_outputs()),
        config_schema=model.model_json_schema(),
        defaults=model().model_dump(mode="json"),
    )


def node_types() -> list[NodeTypeOut]:
    return [describe(t) for t in node_registry().all()]


def uses_secrets(graph: WorkflowGraph) -> bool:
    return any("{{secret." in json.dumps(n.config).replace(" ", "") for n in graph.nodes)


class WorkflowService:
    def __init__(self, db: AsyncSession, runtime: ExecutionRuntime | None = None) -> None:
        self._db = db
        self._runtime = runtime
        self._audit = AuditService(db)
        self._registry = node_registry()

    # ------------------------------------------------------------------ queries
    async def _project(self, owner_id: uuid.UUID, project_id: uuid.UUID) -> Project:
        project = await self._db.scalar(
            select(Project).where(Project.id == project_id, Project.owner_id == owner_id)
        )
        if project is None:
            raise NotFoundError("Project not found.")
        return project

    async def get(self, owner_id: uuid.UUID, workflow_id: uuid.UUID) -> Workflow:
        workflow = await self._db.scalar(
            select(Workflow)
            .options(selectinload(Workflow.versions))
            .where(Workflow.id == workflow_id, Workflow.owner_id == owner_id)
            .execution_options(populate_existing=True)
        )
        if workflow is None:
            raise NotFoundError("Workflow not found.")
        return workflow

    async def list_workflows(
        self, owner_id: uuid.UUID, project_id: uuid.UUID | None = None
    ) -> list[tuple[Workflow, str, WorkflowExecution | None]]:
        query = (
            select(Workflow, Project.name)
            .join(Project, Workflow.project_id == Project.id)
            .options(selectinload(Workflow.versions))
            .where(Workflow.owner_id == owner_id)
            .order_by(Workflow.updated_at.desc())
        )
        if project_id is not None:
            query = query.where(Workflow.project_id == project_id)
        rows = [(w, name) for w, name in (await self._db.execute(query)).all()]
        last: dict[uuid.UUID, WorkflowExecution] = {}
        if rows:
            executions = (
                await self._db.execute(
                    select(WorkflowExecution)
                    .where(WorkflowExecution.workflow_id.in_([w.id for w, _ in rows]))
                    .order_by(WorkflowExecution.created_at.desc())
                )
            ).scalars()
            for execution in executions:
                if execution.workflow_id is not None:
                    last.setdefault(execution.workflow_id, execution)
        return [(w, name, last.get(w.id)) for w, name in rows]

    @staticmethod
    def latest(workflow: Workflow) -> WorkflowVersion:
        return max(workflow.versions, key=lambda v: v.version)

    async def validation_context(self, project: Project) -> ValidationContext:
        environments = (
            await self._db.execute(
                select(ProjectEnvironment)
                .options(selectinload(ProjectEnvironment.variables))
                .where(ProjectEnvironment.project_id == project.id)
            )
        ).scalars()
        names: dict[str, set[str]] = {}
        secrets: dict[str, set[str]] = {}
        for env in environments:
            names[env.name] = {v.name for v in env.variables}
            secrets[env.name] = {v.name for v in env.variables if v.is_secret}
        cases = (
            await self._db.execute(
                select(TestCase.id, TestCase.name, TestVersion.version)
                .join(TestSuite, TestCase.suite_id == TestSuite.id)
                .outerjoin(TestVersion, TestCase.current_version_id == TestVersion.id)
                .where(TestSuite.project_id == project.id)
            )
        ).all()
        return ValidationContext(
            allowed_domains=list(project.allowed_domains),
            environments=names,
            secret_names=secrets,
            test_cases={str(c.id): (c.name, c.version) for c in cases},
        )

    async def issues(self, project: Project, graph: WorkflowGraph) -> list[GraphIssue]:
        return validate_graph(graph, self._registry, await self.validation_context(project))

    async def version_issues(self, workflow: Workflow) -> list[GraphIssue]:
        project = await self._db.get(Project, workflow.project_id)
        assert project is not None
        return await self.issues(project, WorkflowGraph.model_validate(self.latest(workflow).graph))

    # ------------------------------------------------------------------ commands
    async def create(
        self, owner_id: uuid.UUID, project_id: uuid.UUID, body: WorkflowCreate, ctx: RequestContext
    ) -> Workflow:
        await self._project(owner_id, project_id)
        workflow = Workflow(
            owner_id=owner_id, project_id=project_id, name=body.name, description=body.description
        )
        self._db.add(workflow)
        await self._flush_unique()
        graph = templates.build(body.template, test_case_id=body.test_case_id)
        self._db.add(
            WorkflowVersion(
                workflow_id=workflow.id,
                version=1,
                graph=graph.model_dump(mode="json"),
                created_by_id=owner_id,
            )
        )
        self._audit.record(
            "workflow.create",
            "success",
            ctx=ctx,
            user_id=owner_id,
            target_type="workflow",
            target_id=str(workflow.id),
            details={"template": body.template},
        )
        await self._db.commit()
        return await self.get(owner_id, workflow.id)

    async def update(
        self, owner_id: uuid.UUID, workflow_id: uuid.UUID, body: WorkflowUpdate
    ) -> Workflow:
        workflow = await self.get(owner_id, workflow_id)
        if body.name is not None:
            workflow.name = " ".join(body.name.split())
        if body.description is not None:
            workflow.description = body.description
        workflow.updated_at = utcnow()
        await self._flush_unique()
        await self._db.commit()
        return await self.get(owner_id, workflow_id)

    async def delete(
        self, owner_id: uuid.UUID, workflow_id: uuid.UUID, ctx: RequestContext
    ) -> None:
        workflow = await self.get(owner_id, workflow_id)
        await self._db.delete(workflow)
        self._audit.record(
            "workflow.delete",
            "success",
            ctx=ctx,
            user_id=owner_id,
            target_type="workflow",
            target_id=str(workflow_id),
        )
        await self._db.commit()

    async def save_version(
        self, owner_id: uuid.UUID, workflow_id: uuid.UUID, graph: WorkflowGraph
    ) -> Workflow:
        workflow = await self.get(owner_id, workflow_id)
        latest = self.latest(workflow)
        if latest.graph == graph.model_dump(mode="json"):
            return workflow  # nothing changed: no new version
        self._db.add(
            WorkflowVersion(
                workflow_id=workflow.id,
                version=latest.version + 1,
                graph=graph.model_dump(mode="json"),
                created_by_id=owner_id,
            )
        )
        workflow.updated_at = utcnow()
        await self._db.commit()
        return await self.get(owner_id, workflow_id)

    async def duplicate(
        self, owner_id: uuid.UUID, workflow_id: uuid.UUID, ctx: RequestContext
    ) -> Workflow:
        source = await self.get(owner_id, workflow_id)
        existing = set(
            (
                await self._db.execute(
                    select(Workflow.name).where(Workflow.project_id == source.project_id)
                )
            ).scalars()
        )
        name, n = f"{source.name} (copy)", 2
        while name in existing:
            name, n = f"{source.name} (copy {n})", n + 1
        copy = Workflow(
            owner_id=owner_id,
            project_id=source.project_id,
            name=name[:120],
            description=source.description,
        )
        self._db.add(copy)
        await self._db.flush()
        self._db.add(
            WorkflowVersion(
                workflow_id=copy.id,
                version=1,
                graph=self.latest(source).graph,
                created_by_id=owner_id,
            )
        )
        self._audit.record(
            "workflow.duplicate",
            "success",
            ctx=ctx,
            user_id=owner_id,
            target_type="workflow",
            target_id=str(copy.id),
            details={"source": str(source.id)},
        )
        await self._db.commit()
        return await self.get(owner_id, copy.id)

    async def start_run(
        self,
        owner_id: uuid.UUID,
        workflow_id: uuid.UUID,
        version_number: int | None,
        ctx: RequestContext,
    ) -> uuid.UUID:
        assert self._runtime is not None
        workflow = await self.get(owner_id, workflow_id)
        version = (
            self.latest(workflow)
            if version_number is None
            else next((v for v in workflow.versions if v.version == version_number), None)
        )
        if version is None:
            raise NotFoundError("Version not found.")
        project = await self._project(owner_id, workflow.project_id)
        graph = WorkflowGraph.model_validate(version.graph)
        issues = await self.issues(project, graph)
        if has_errors(issues):
            raise WorkflowRejectedError(
                "Fix the highlighted problems before running the workflow.",
                details={"issues": [i.model_dump() for i in issues]},
            )
        active = await self._db.scalar(
            select(func.count())
            .select_from(WorkflowExecution)
            .where(
                WorkflowExecution.owner_id == owner_id,
                WorkflowExecution.status.in_(("queued", "running")),
            )
        )
        settings = self._runtime.settings
        if (active or 0) >= settings.max_active_runs_per_user:
            raise TooManyRunsError(f"You already have {active} runs in progress.")
        secret = uses_secrets(graph)
        notes: list[str] = []
        if secret:
            notes.append(
                "Traces and video are off for this run because it types secret values. "
                "Screenshots mask those fields."
            )
        if not self._runtime.isolated:
            notes.append(
                "Development mode: the browser runs inside the API process without container "
                "isolation."
            )
        now = utcnow()
        execution = WorkflowExecution(
            owner_id=owner_id,
            project_id=project.id,
            kind="workflow",
            status="queued",
            trigger="manual",
            workflow_id=workflow.id,
            workflow_version_id=version.id,
            snapshot={
                "template": "workflow",
                "engine": "m5",
                "workflow_name": workflow.name,
                "version": version.version,
                "isolated": self._runtime.isolated,
                "uses_secrets": secret,
                "notes": notes,
                "capture": {},
            },
            created_at=now,
        )
        self._db.add(execution)
        await self._db.flush()
        for node in graph.nodes:
            node_type = self._registry.get(node.type)
            self._db.add(
                NodeExecution(
                    execution_id=execution.id,
                    node_id=node.id,
                    node_type=node.type,
                    label=(node.label or (node_type.label if node_type else node.type))[:120],
                    status="waiting",
                )
            )
        for seq, (type_, message) in enumerate(
            [
                ("execution.created", f"Run of workflow {workflow.name} v{version.version}"),
                ("execution.queued", "Waiting for a worker"),
            ],
            start=1,
        ):
            self._db.add(
                ExecutionEvent(
                    execution_id=execution.id,
                    seq=seq,
                    ts=now,
                    type=type_,
                    category="system",
                    level="info",
                    message=message,
                    data={},
                )
            )
        self._audit.record(
            "workflow.run.start",
            "success",
            ctx=ctx,
            user_id=owner_id,
            target_type="execution",
            target_id=str(execution.id),
            details={"workflow_id": str(workflow.id), "version": version.version},
        )
        await self._db.commit()
        try:
            await self._runtime.jobs.enqueue(execution.id)
        except Exception as exc:
            logger.exception("Could not queue execution %s", execution.id)
            execution.status, execution.finished_at = "error", utcnow()
            execution.error_code = "run.queue_unavailable"
            execution.error_message = "The run could not be queued."
            await self._db.commit()
            raise RunQueueUnavailableError() from exc
        return execution.id

    async def _flush_unique(self) -> None:
        try:
            await self._db.flush()
        except IntegrityError as exc:
            await self._db.rollback()
            raise ConflictError("A workflow with this name already exists in the project.") from exc
