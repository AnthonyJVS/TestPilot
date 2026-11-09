"""Workflow Studio API: node types, workflows, immutable versions, validation, duplicate, run."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.dependencies import Ctx, CurrentUser, DbSession
from app.api.routes.executions import Runtime, _execution_out
from app.domain.workflow import WorkflowGraph
from app.infrastructure.database.models import Workflow
from app.schemas.execution import ExecutionOut
from app.schemas.workflow import (
    GraphIn,
    NodeTypeOut,
    ValidationOut,
    VersionSummary,
    WorkflowCreate,
    WorkflowOut,
    WorkflowRunCreate,
    WorkflowSummaryOut,
    WorkflowUpdate,
    WorkflowVersionOut,
)
from app.services.execution.execution_service import ExecutionService
from app.services.workflows.validation import has_errors
from app.services.workflows.workflow_service import WorkflowService, node_types

router = APIRouter(tags=["workflows"])


def get_workflow_service(db: DbSession, runtime: Runtime) -> WorkflowService:
    return WorkflowService(db, runtime)


Workflows = Annotated[WorkflowService, Depends(get_workflow_service)]


async def _out(service: WorkflowService, workflow: Workflow) -> WorkflowOut:
    latest = service.latest(workflow)
    return WorkflowOut(
        id=workflow.id,
        project_id=workflow.project_id,
        name=workflow.name,
        description=workflow.description,
        latest=WorkflowVersionOut(
            id=latest.id,
            version=latest.version,
            graph=WorkflowGraph.model_validate(latest.graph),
            issues=await service.version_issues(workflow),
            created_at=latest.created_at,
        ),
        versions=[
            VersionSummary(id=v.id, version=v.version, created_at=v.created_at)
            for v in sorted(workflow.versions, key=lambda v: -v.version)
        ],
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


@router.get("/workflow-node-types", response_model=list[NodeTypeOut])
async def list_node_types(_: CurrentUser) -> list[NodeTypeOut]:
    return node_types()


@router.get("/workflows", response_model=list[WorkflowSummaryOut])
async def list_workflows(
    user: CurrentUser, workflows: Workflows, project_id: uuid.UUID | None = None
) -> list[WorkflowSummaryOut]:
    rows = await workflows.list_workflows(user.id, project_id)
    result = []
    for workflow, project_name, last in rows:
        latest = workflows.latest(workflow)
        result.append(
            WorkflowSummaryOut(
                id=workflow.id,
                project_id=workflow.project_id,
                project_name=project_name,
                name=workflow.name,
                description=workflow.description,
                latest_version=latest.version,
                nodes=len(latest.graph.get("nodes", [])),
                updated_at=workflow.updated_at,
                last_run_status=last.status if last else None,
                last_run_at=last.created_at if last else None,
            )
        )
    return result


@router.post(
    "/projects/{project_id}/workflows",
    response_model=WorkflowOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_workflow(
    project_id: uuid.UUID, body: WorkflowCreate, user: CurrentUser, workflows: Workflows, ctx: Ctx
) -> WorkflowOut:
    return await _out(workflows, await workflows.create(user.id, project_id, body, ctx))


@router.get("/workflows/{workflow_id}", response_model=WorkflowOut)
async def get_workflow(
    workflow_id: uuid.UUID, user: CurrentUser, workflows: Workflows
) -> WorkflowOut:
    return await _out(workflows, await workflows.get(user.id, workflow_id))


@router.patch("/workflows/{workflow_id}", response_model=WorkflowOut)
async def update_workflow(
    workflow_id: uuid.UUID, body: WorkflowUpdate, user: CurrentUser, workflows: Workflows
) -> WorkflowOut:
    return await _out(workflows, await workflows.update(user.id, workflow_id, body))


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: uuid.UUID, user: CurrentUser, workflows: Workflows, ctx: Ctx
) -> Response:
    await workflows.delete(user.id, workflow_id, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/workflows/{workflow_id}/versions", response_model=WorkflowOut, status_code=201)
async def save_version(
    workflow_id: uuid.UUID, body: GraphIn, user: CurrentUser, workflows: Workflows
) -> WorkflowOut:
    return await _out(workflows, await workflows.save_version(user.id, workflow_id, body.graph))


@router.post("/workflows/{workflow_id}/validate", response_model=ValidationOut)
async def validate_workflow(
    workflow_id: uuid.UUID, body: GraphIn, user: CurrentUser, workflows: Workflows, db: DbSession
) -> ValidationOut:
    workflow = await workflows.get(user.id, workflow_id)
    from app.infrastructure.database.models import Project

    project = await db.get(Project, workflow.project_id)
    assert project is not None
    issues = await workflows.issues(project, body.graph)
    return ValidationOut(issues=issues, runnable=not has_errors(issues))


@router.post("/workflows/{workflow_id}/duplicate", response_model=WorkflowOut, status_code=201)
async def duplicate_workflow(
    workflow_id: uuid.UUID, user: CurrentUser, workflows: Workflows, ctx: Ctx
) -> WorkflowOut:
    return await _out(workflows, await workflows.duplicate(user.id, workflow_id, ctx))


@router.post("/workflows/{workflow_id}/run", response_model=ExecutionOut, status_code=202)
async def run_workflow(
    workflow_id: uuid.UUID,
    body: WorkflowRunCreate,
    user: CurrentUser,
    workflows: Workflows,
    db: DbSession,
    runtime: Runtime,
    ctx: Ctx,
) -> ExecutionOut:
    execution_id = await workflows.start_run(user.id, workflow_id, body.version, ctx)
    executions = ExecutionService(db, runtime)
    execution = await executions.get(user.id, execution_id)
    return _execution_out(execution, await executions.workflow_graph(execution))
