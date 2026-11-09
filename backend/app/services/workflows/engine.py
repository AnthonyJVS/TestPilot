"""Workflow DAG engine (docs/WORKFLOW_ENGINE.md §4).

* A node is ready when all incoming edges are resolved. With at least one active edge it runs;
  with none it is skipped and its outgoing edges become inactive (skip propagation).
* Ready nodes start in topological order (node ID tie-break) up to ``MAX_PARALLEL``.
* Each attempt is bounded by the node timeout; transient errors (or any, if configured) are
  retried with the node's backoff policy.
* A failed node with a connected ``error`` handle routes its error payload there and the run
  continues; otherwise the run fails, running nodes are cancelled and the rest are skipped.
* Cancellation is cooperative: the flag is polled, browser sessions are closed (aborting their
  in-flight action) and running nodes are cancelled.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.crypto import EncryptedSecret, SecretCipher
from app.domain.workflow import GraphEdge, GraphNode, WorkflowGraph
from app.infrastructure.database.base import utcnow
from app.infrastructure.database.models import (
    ExecutionEvent,
    NodeExecution,
    Project,
    ProjectEnvironment,
    WorkflowExecution,
    WorkflowVersion,
)
from app.services.ai.registry import ProviderRegistry
from app.services.execution.browser_client import BrowserClient
from app.services.execution.events import EventNotifier, EventRecorder
from app.services.execution.test_data import Variable
from app.services.project_service import secret_aad
from app.services.workflows.context import Environment, RunContext
from app.services.workflows.registry import NodeError, NodeRegistry, NodeResult, NodeRun, NodeType
from app.services.workflows.validation import topological_order

logger = logging.getLogger(__name__)

MAX_PARALLEL = 4
CANCEL_POLL_SECONDS = 1.0
MAX_OUTPUT_CHARS = 20_000


@dataclass
class _Outcome:
    node_id: str
    result: NodeResult | None = None
    error: NodeError | None = None


class _RunFailed(Exception):
    pass


def _preview(value: Any, scrub: Any) -> dict[str, Any]:
    """JSON-safe, scrubbed, size-limited copy of node outputs for the inspector."""
    try:
        text = json.dumps(value, default=str)
    except (TypeError, ValueError):
        text = json.dumps(str(value))
    text = scrub(text)
    if len(text) > MAX_OUTPUT_CHARS:
        return {"truncated": True, "preview": text[:2000]}
    loaded: dict[str, Any] = json.loads(text) if text.startswith("{") else {"value": text}
    return loaded


class WorkflowOrchestrator:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        cipher: SecretCipher,
        browser: BrowserClient,
        notifier: EventNotifier,
        providers: ProviderRegistry,
        nodes: NodeRegistry,
    ) -> None:
        self._sf = session_factory
        self._settings = settings
        self._cipher = cipher
        self._browser = browser
        self._notifier = notifier
        self._providers = providers
        self._nodes = nodes

    async def execute(self, execution_id: uuid.UUID) -> None:
        async with self._sf() as db:
            claimed = await db.execute(
                update(WorkflowExecution)
                .where(WorkflowExecution.id == execution_id, WorkflowExecution.status == "queued")
                .values(status="running", started_at=utcnow())
            )
            await db.commit()
            if claimed.rowcount == 0:  # type: ignore[attr-defined]
                return
            execution = (
                await db.execute(
                    select(WorkflowExecution)
                    .options(selectinload(WorkflowExecution.node_executions))
                    .where(WorkflowExecution.id == execution_id)
                )
            ).scalar_one()
            last_seq = await db.scalar(
                select(func.max(ExecutionEvent.seq)).where(
                    ExecutionEvent.execution_id == execution_id
                )
            )
            recorder = EventRecorder(db, self._notifier, execution_id, last_seq or 0)
            status = "error"
            code: str | None = "internal"
            message: str | None = "The run stopped because of an error."
            ctx: RunContext | None = None
            try:
                version = await db.get(WorkflowVersion, execution.workflow_version_id)
                project = await db.get(Project, execution.project_id)
                if version is None or project is None:
                    raise _RunFailed("The workflow version or project was deleted.")
                graph = WorkflowGraph.model_validate(version.graph)
                ctx = RunContext(
                    db=db,
                    recorder=recorder,
                    execution=execution,
                    settings=self._settings,
                    session_factory=self._sf,
                    cipher=self._cipher,
                    providers=self._providers,
                    browser=self._browser,
                    allowed_domains=list(project.allowed_domains),
                    environments=await self._environments(db, project.id),
                    uses_secrets=bool(execution.snapshot.get("uses_secrets")),
                )
                await ctx.emit(
                    "execution.started",
                    f"Workflow {execution.snapshot.get('workflow_name', '')} "
                    f"v{execution.snapshot.get('version', '?')} started",
                )
                for note in execution.snapshot.get("notes", []):
                    await ctx.emit("execution.notice", note, level="warning")
                status, code, message = await self._schedule(ctx, graph, execution)
            except _RunFailed as exc:
                status, code, message = "error", "run.stale", str(exc)
            except Exception:
                logger.exception("Workflow execution %s crashed", execution_id)
                await db.rollback()
            finally:
                if ctx is not None:
                    with contextlib.suppress(Exception):
                        await ctx.close_sessions()
            await self._finish(db, recorder, execution, status, code, message)

    # ------------------------------------------------------------------ scheduling
    async def _schedule(
        self, ctx: RunContext, graph: WorkflowGraph, execution: WorkflowExecution
    ) -> tuple[str, str | None, str | None]:
        order = topological_order(graph) or [n.id for n in graph.nodes]
        nodes = {n.id: n for n in graph.nodes}
        rows = {r.node_id: r for r in execution.node_executions}
        incoming: dict[str, list[GraphEdge]] = defaultdict(list)
        outgoing: dict[str, list[GraphEdge]] = defaultdict(list)
        for edge in graph.edges:
            incoming[edge.target].append(edge)
            outgoing[edge.source].append(edge)
        edge_state: dict[str, tuple[bool, Any] | None] = {e.id: None for e in graph.edges}
        state = {node_id: "waiting" for node_id in order}
        running: dict[asyncio.Task[Any], str] = {}
        started = time.monotonic()
        failure: tuple[str, str] | None = None
        cancel_task = asyncio.create_task(self._wait_for_cancel(execution.id))
        cancelled = False

        def resolve(node_id: str, active_handles: dict[str, Any] | None) -> None:
            for edge in outgoing[node_id]:
                if active_handles is not None and edge.source_handle in active_handles:
                    edge_state[edge.id] = (True, active_handles[edge.source_handle])
                else:
                    edge_state[edge.id] = (False, None)

        try:
            while True:
                if failure is None and not cancelled:
                    changed = True
                    while changed:
                        changed = False
                        for node_id in order:
                            if state[node_id] != "waiting" or len(running) >= MAX_PARALLEL:
                                continue
                            edges_in = incoming[node_id]
                            if any(edge_state[e.id] is None for e in edges_in):
                                continue
                            active = [e for e in edges_in if (edge_state[e.id] or (False,))[0]]
                            if edges_in and not active:
                                state[node_id] = "skipped"
                                resolve(node_id, None)
                                await self._mark(ctx, rows[node_id], "skipped", "No active input")
                                changed = True
                                continue
                            node = nodes[node_id]
                            node_type = self._nodes.get(node.type)
                            if node_type is None:  # validated before the run
                                raise _RunFailed(f"Unknown node type {node.type}.")
                            state[node_id] = "running"
                            inputs = self._inputs(node_type, active, edge_state)
                            task = asyncio.create_task(
                                self._run_node(ctx, node, node_type, inputs, rows[node_id])
                            )
                            running[task] = node_id
                if not running:
                    break
                remaining = self._settings.run_max_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    await self._cancel_running(ctx, running, rows, state)
                    self._skip_waiting(state)
                    await self._settle(ctx, rows, state)
                    return (
                        "error",
                        "run.timeout",
                        f"The workflow exceeded {self._settings.run_max_seconds} seconds.",
                    )
                done, _ = await asyncio.wait(
                    {*running, cancel_task}, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
                )
                if cancel_task in done:
                    cancelled = True
                    await ctx.close_sessions()
                    await self._cancel_running(ctx, running, rows, state)
                    break
                for task in done:
                    node_id = running.pop(task)
                    outcome = task.result()
                    if outcome.result is not None:
                        state[node_id] = "completed"
                        resolve(node_id, outcome.result.outputs)
                        continue
                    state[node_id] = "failed"
                    error = outcome.error or NodeError("node.failed", "The node failed.")
                    error_edges = [e for e in outgoing[node_id] if e.source_handle == "error"]
                    if error_edges:
                        resolve(
                            node_id,
                            {
                                "error": {
                                    "node_id": node_id,
                                    "code": error.code,
                                    "message": error.message,
                                }
                            },
                        )
                    elif failure is None:
                        failure = (
                            error.code,
                            f"{nodes[node_id].label or node_id}: {error.message}",
                        )
                if failure is not None and running:
                    await self._cancel_running(ctx, running, rows, state)
        finally:
            cancel_task.cancel()
        if cancelled:
            for node_id, value in state.items():
                if value == "waiting":
                    state[node_id] = "cancelled"
                    await self._mark(ctx, rows[node_id], "cancelled", "Run cancelled")
            return "cancelled", "run.cancelled", "The run was cancelled."
        self._skip_waiting(state)
        await self._settle(ctx, rows, state)
        if failure is not None:
            return "failed", failure[0], failure[1]
        return "passed", None, None

    @staticmethod
    def _inputs(
        node_type: NodeType, active: list[GraphEdge], edge_state: dict[str, tuple[bool, Any] | None]
    ) -> dict[str, Any]:
        inputs: dict[str, Any] = {}
        for port in node_type.inputs:
            values = [
                (edge_state[e.id] or (False, None))[1]
                for e in active
                if e.target_handle == port.name
            ]
            if port.multi:
                inputs[port.name] = values
            elif values:
                inputs[port.name] = values[0]
        return inputs

    @staticmethod
    def _skip_waiting(state: dict[str, str]) -> None:
        for node_id, value in state.items():
            if value == "waiting":
                state[node_id] = "skip_pending"

    async def _settle(
        self, ctx: RunContext, rows: dict[str, NodeExecution], state: dict[str, str]
    ) -> None:
        for node_id, value in state.items():
            if value == "skip_pending":
                state[node_id] = "skipped"
                await self._mark(ctx, rows[node_id], "skipped", "Not reached")

    async def _cancel_running(
        self,
        ctx: RunContext,
        running: dict[asyncio.Task[Any], str],
        rows: dict[str, NodeExecution],
        state: dict[str, str],
    ) -> None:
        for task in running:
            task.cancel()
        for task, node_id in list(running.items()):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
            state[node_id] = "cancelled"
            await self._mark(ctx, rows[node_id], "cancelled", "Stopped")
        running.clear()

    async def _mark(self, ctx: RunContext, row: NodeExecution, status: str, why: str) -> None:
        now = utcnow()
        await ctx.update_node(
            row,
            status=status,
            summary=why,
            finished_at=now if status != "skipped" else None,
            duration_ms=int((now - row.started_at).total_seconds() * 1000)
            if row.started_at and status == "cancelled"
            else row.duration_ms,
        )
        await ctx.emit(
            f"node.{status}",
            f"{row.label}: {why.lower()}",
            category="node",
            level="warning" if status == "cancelled" else "info",
            node_id=row.node_id,
        )

    # ------------------------------------------------------------------ nodes
    async def _run_node(
        self,
        ctx: RunContext,
        node: GraphNode,
        node_type: NodeType,
        inputs: dict[str, Any],
        row: NodeExecution,
    ) -> _Outcome:
        label = node.label or node_type.label
        started = utcnow()
        await ctx.update_node(row, status="running", started_at=started, attempts=0)
        await ctx.emit(
            "node.started",
            f"{label} started",
            category="node",
            node_id=node.id,
            data={"type": node.type},
        )
        timeout = node.timeout_seconds or self._settings.run_max_seconds
        policy = node.retry
        attempt = 0
        while True:
            attempt += 1
            await ctx.update_node(row, attempts=attempt)
            try:
                config = node_type.config_model.model_validate(node.config)
                result = await asyncio.wait_for(
                    node_type.execute(NodeRun(node, config, inputs, ctx, attempt)), timeout
                )
            except NodeError as exc:
                error = exc
            except TimeoutError:
                error = NodeError(
                    "node.timeout", f"Did not finish within {timeout} seconds.", transient=True
                )
            except ValidationError as exc:
                error = NodeError("node.invalid_config", str(exc)[:500])
            except Exception:
                logger.exception("Node %s crashed", node.id)
                error = NodeError("node.internal", "The node hit an internal error.")
            else:
                finished = utcnow()
                await ctx.update_node(
                    row,
                    status="completed",
                    finished_at=finished,
                    duration_ms=int((finished - started).total_seconds() * 1000),
                    summary=result.summary[:300] or None,
                    output=_preview(result.outputs, ctx.scrubber.text),
                )
                await ctx.emit(
                    "node.completed",
                    f"{label} completed" + (f": {result.summary}" if result.summary else ""),
                    category="node",
                    node_id=node.id,
                    data={"handles": sorted(result.outputs), "attempt": attempt},
                )
                return _Outcome(node.id, result=result)
            error.message = ctx.scrubber.text(error.message)
            if attempt < policy.max_attempts and (policy.retry_on == "any" or error.transient):
                delay = policy.delay(attempt)
                await ctx.emit(
                    "node.retry_scheduled",
                    f"{label} attempt {attempt} failed ({error.message[:200]}); "
                    f"retrying in {delay:g}s",
                    category="node",
                    level="warning",
                    node_id=node.id,
                    data={"attempt": attempt, "delay_seconds": delay, "code": error.code},
                )
                await asyncio.sleep(delay)
                continue
            finished = utcnow()
            await ctx.update_node(
                row,
                status="failed",
                finished_at=finished,
                duration_ms=int((finished - started).total_seconds() * 1000),
                error_code=error.code,
                error_message=error.message,
            )
            await ctx.emit(
                "node.failed",
                f"{label} failed: {error.message}",
                category="node",
                level="error",
                node_id=node.id,
                data={"code": error.code, "attempts": attempt},
            )
            return _Outcome(node.id, error=error)

    # ------------------------------------------------------------------ helpers
    async def _wait_for_cancel(self, execution_id: uuid.UUID) -> None:
        # Polls the database: the cancel request may come from another process.
        while True:
            async with self._sf() as db:
                requested = await db.scalar(
                    select(WorkflowExecution.cancel_requested_at).where(
                        WorkflowExecution.id == execution_id
                    )
                )
            if requested is not None:
                return
            await asyncio.sleep(CANCEL_POLL_SECONDS)

    async def _environments(
        self, db: AsyncSession, project_id: uuid.UUID
    ) -> dict[str, Environment]:
        project = await db.get(Project, project_id)
        assert project is not None
        rows = (
            await db.execute(
                select(ProjectEnvironment)
                .options(selectinload(ProjectEnvironment.variables))
                .where(ProjectEnvironment.project_id == project_id)
            )
        ).scalars()
        environments: dict[str, Environment] = {}
        for env in rows:
            variables: dict[str, Variable] = {}
            for item in env.variables:
                if item.is_secret:
                    if item.ciphertext is None or item.nonce is None or item.key_id is None:
                        continue
                    value = self._cipher.decrypt(
                        EncryptedSecret(item.ciphertext, item.nonce, item.key_id),
                        associated_data=secret_aad(env.id, item.name),
                    )
                else:
                    value = item.value or ""
                variables[item.name] = Variable(item.name, value, item.is_secret)
            environments[env.name] = Environment(
                env.id, env.name, (env.base_url or project.base_url).rstrip("/"), variables
            )
        return environments

    async def _finish(
        self,
        db: AsyncSession,
        recorder: EventRecorder,
        execution: WorkflowExecution,
        status: str,
        code: str | None,
        message: str | None,
    ) -> None:
        now = utcnow()
        await db.execute(
            update(NodeExecution)
            .where(
                NodeExecution.execution_id == execution.id,
                NodeExecution.status.in_(("waiting", "running")),
            )
            .values(status="skipped" if status != "cancelled" else "cancelled")
        )
        await db.commit()
        await db.refresh(execution)
        await db.refresh(execution, ["node_executions"])
        execution.status = status
        execution.finished_at = now
        if execution.started_at is not None:
            execution.duration_ms = int((now - execution.started_at).total_seconds() * 1000)
        execution.error_code, execution.error_message = code, message
        completed = sum(1 for n in execution.node_executions if n.status == "completed")
        summary = f"{completed}/{len(execution.node_executions)} nodes completed"
        if status == "passed":
            recorder.add(
                "execution.completed", f"Workflow completed: {summary}", data={"status": status}
            )
        elif status == "cancelled":
            recorder.add(
                "execution.cancelled", "Run cancelled", level="warning", data={"status": status}
            )
        else:
            recorder.add(
                "execution.failed",
                message or "Workflow failed",
                level="error",
                data={"status": status, "code": code, "summary": summary},
            )
        await recorder.flush()
