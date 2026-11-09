"""Executions API: start runs, history, details, events (REST + SSE), cancel, artifacts."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse

from app.api.dependencies import Ctx, CurrentUser, DbSession
from app.infrastructure.database.models import (
    ExecutionArtifact,
    ExecutionEvent,
    TestExecution,
    WorkflowExecution,
)
from app.infrastructure.database.models.execution import TERMINAL_STATUSES
from app.schemas.execution import (
    ArtifactOut,
    ExecutionEventOut,
    ExecutionOut,
    ExecutionRuntimeOut,
    ExecutionStepOut,
    ExecutionSummaryOut,
    RunCreate,
    TestExecutionOut,
)
from app.services.execution.execution_service import ExecutionService, fetch_events
from app.services.execution.runtime import ExecutionRuntime
from browser_worker.protocol import WorkerError

router = APIRouter(tags=["executions"])

STREAM_MAX_SECONDS = 600  # clients reconnect with Last-Event-ID (and a fresh token)
KEEPALIVE_SECONDS = 15.0
INLINE_CONTENT_TYPES = {"image/png", "image/jpeg"}


def get_runtime(request: Request) -> ExecutionRuntime:
    runtime: ExecutionRuntime = request.app.state.execution
    return runtime


Runtime = Annotated[ExecutionRuntime, Depends(get_runtime)]


def get_execution_service(db: DbSession, runtime: Runtime) -> ExecutionService:
    return ExecutionService(db, runtime)


Executions = Annotated[ExecutionService, Depends(get_execution_service)]


# ------------------------------------------------------------------ mappers


def _test_out(test: TestExecution) -> TestExecutionOut:
    return TestExecutionOut(
        id=test.id,
        test_case_id=test.test_case_id,
        test_version_id=test.test_version_id,
        environment_id=test.environment_id,
        test_name=test.test_name,
        version_number=test.version_number,
        environment_name=test.environment_name,
        base_url=test.base_url,
        browser=test.browser,
        browser_version=test.browser_version,
        status=test.status,
        steps_total=test.steps_total,
        steps_passed=test.steps_passed,
        steps_failed=test.steps_failed,
        started_at=test.started_at,
        finished_at=test.finished_at,
        duration_ms=test.duration_ms,
        steps=[ExecutionStepOut.model_validate(s, from_attributes=True) for s in test.steps],
    )


def _artifact_out(artifact: ExecutionArtifact) -> ArtifactOut:
    return ArtifactOut.model_validate(artifact, from_attributes=True)


def _execution_out(execution: WorkflowExecution) -> ExecutionOut:
    snapshot = execution.snapshot
    return ExecutionOut(
        id=execution.id,
        project_id=execution.project_id,
        kind="test_run",
        status=execution.status,
        trigger=execution.trigger,
        error_code=execution.error_code,
        error_message=execution.error_message,
        cancel_requested=execution.cancel_requested_at is not None,
        created_at=execution.created_at,
        started_at=execution.started_at,
        finished_at=execution.finished_at,
        duration_ms=execution.duration_ms,
        isolated=bool(snapshot.get("isolated")),
        notes=list(snapshot.get("notes", [])),
        capture=dict(snapshot.get("capture", {})),
        test=_test_out(execution.test_executions[0]),
        artifacts=[_artifact_out(a) for a in execution.artifacts],
    )


def _summary_out(execution: WorkflowExecution, test: TestExecution) -> ExecutionSummaryOut:
    return ExecutionSummaryOut(
        id=execution.id,
        project_id=execution.project_id,
        kind="test_run",
        status=execution.status,
        test_case_id=test.test_case_id,
        test_name=test.test_name,
        version_number=test.version_number,
        environment_name=test.environment_name,
        browser=test.browser,
        steps_total=test.steps_total,
        steps_passed=test.steps_passed,
        error_message=execution.error_message,
        created_at=execution.created_at,
        started_at=execution.started_at,
        finished_at=execution.finished_at,
        duration_ms=execution.duration_ms,
    )


def _event_out(event: ExecutionEvent) -> ExecutionEventOut:
    return ExecutionEventOut.model_validate(event, from_attributes=True)


# ------------------------------------------------------------------ routes


@router.get("/execution-runtime", response_model=ExecutionRuntimeOut)
async def execution_runtime(_: CurrentUser, runtime: Runtime) -> ExecutionRuntimeOut:
    settings = runtime.settings
    available, detail, version, browsers = True, None, None, {}
    try:
        info = await runtime.browser.info()
        version, browsers = info.playwright_version, info.browsers
    except WorkerError as exc:
        available, detail = False, exc.message
    return ExecutionRuntimeOut(
        mode=settings.execution_mode,
        transport=settings.browser_transport,
        isolated=runtime.isolated,
        available=available and any(browsers.values()),
        detail=detail,
        playwright_version=version,
        browsers=browsers,
        allow_private_network=settings.browser_allow_private_network,
        max_run_seconds=settings.run_max_seconds,
    )


@router.post(
    "/versions/{version_id}/run",
    response_model=ExecutionOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_version(
    version_id: uuid.UUID, body: RunCreate, user: CurrentUser, executions: Executions, ctx: Ctx
) -> ExecutionOut:
    return _execution_out(await executions.start_test_run(user.id, version_id, body, ctx))


@router.get("/executions", response_model=list[ExecutionSummaryOut])
async def list_executions(
    user: CurrentUser,
    executions: Executions,
    project_id: uuid.UUID | None = None,
    test_case_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ExecutionSummaryOut]:
    rows = await executions.list_runs(
        user.id, project_id=project_id, test_case_id=test_case_id, limit=limit
    )
    return [_summary_out(execution, test) for execution, test in rows]


@router.get("/executions/{execution_id}", response_model=ExecutionOut)
async def get_execution(
    execution_id: uuid.UUID, user: CurrentUser, executions: Executions
) -> ExecutionOut:
    return _execution_out(await executions.get(user.id, execution_id))


@router.post("/executions/{execution_id}/cancel", response_model=ExecutionOut)
async def cancel_execution(
    execution_id: uuid.UUID, user: CurrentUser, executions: Executions, ctx: Ctx
) -> ExecutionOut:
    return _execution_out(await executions.cancel(user.id, execution_id, ctx))


@router.get("/executions/{execution_id}/events", response_model=list[ExecutionEventOut])
async def list_events(
    execution_id: uuid.UUID,
    user: CurrentUser,
    executions: Executions,
    after_seq: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> list[ExecutionEventOut]:
    events = await executions.events(user.id, execution_id, after_seq=after_seq, limit=limit)
    return [_event_out(e) for e in events]


@router.get(
    "/executions/{execution_id}/events/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream_events(
    execution_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    executions: Executions,
    runtime: Runtime,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    after_seq: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    """Server-Sent Events: replays persisted events after ``Last-Event-ID``, then tails live."""
    await executions.events(user.id, execution_id, after_seq=0, limit=1)  # ownership (404)
    await db.close()  # release the connection; the stream uses short-lived sessions
    start = after_seq
    if last_event_id and last_event_id.isdigit():
        start = max(start, int(last_event_id))
    session_factory = request.app.state.session_factory

    async def generate() -> AsyncIterator[str]:
        last = start
        deadline = time.monotonic() + STREAM_MAX_SECONDS
        yield "retry: 2000\n\n"
        async with runtime.notifier.subscribe(execution_id) as subscription:
            while time.monotonic() < deadline and not await request.is_disconnected():
                async with session_factory() as session:
                    events = await fetch_events(session, execution_id, after_seq=last, limit=200)
                    current = await session.get(WorkflowExecution, execution_id)
                for event in events:
                    payload = _event_out(event).model_dump_json()
                    yield f"id: {event.seq}\nevent: {event.type}\ndata: {payload}\n\n"
                    last = event.seq
                if events:
                    continue
                if current is None or current.status in TERMINAL_STATUSES:
                    yield f"event: end\ndata: {json.dumps({'last_seq': last})}\n\n"
                    return
                if not await subscription.wait(KEEPALIVE_SECONDS):
                    yield ": keepalive\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/artifacts/{artifact_id}/content",
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def artifact_content(
    artifact_id: uuid.UUID, user: CurrentUser, executions: Executions
) -> FileResponse:
    artifact, path = await executions.artifact(user.id, artifact_id)
    inline = artifact.content_type in INLINE_CONTENT_TYPES
    return FileResponse(
        path,
        media_type=artifact.content_type,
        filename=artifact.name,
        content_disposition_type="inline" if inline else "attachment",
        headers={"Cache-Control": "private, no-store"},
    )
