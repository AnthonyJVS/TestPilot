"""Self-contained HTML run reports (milestone 8).

One file per run: status, steps or nodes, screenshots embedded as data URIs, problems from the
console and network, the failure analysis (verified evidence kept apart from AI hypotheses) and
every AI call with its provider and model. Everything is escaped and the file forbids scripts
through its own Content-Security-Policy. It contains no secret values: it is built from records
that were scrubbed before they were stored.
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.base import utcnow
from app.infrastructure.database.models import (
    AIRequest,
    ExecutionArtifact,
    ExecutionEvent,
    FailureAnalysis,
    Project,
    RepairProposal,
    WorkflowExecution,
)

MAX_IMAGE_BYTES = 600_000
MAX_TOTAL_IMAGE_BYTES = 10_000_000
MAX_PROBLEMS = 30

CSS = """
:root{color-scheme:light;--ink:#0f172a;--muted:#475569;--faint:#94a3b8;--line:#e2e8f0;
--ok:#15803d;--bad:#b91c1c;--warn:#b45309;--beacon:#d97706;--panel:#f8fafc}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;
color:var(--ink);background:#fff}main{max-width:1000px;margin:0 auto;padding:32px 24px 64px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:17px;margin:32px 0 10px;padding-bottom:6px;
border-bottom:1px solid var(--line)}h3{font-size:14px;margin:16px 0 6px}
.muted{color:var(--muted)}.faint{color:var(--faint)}.mono{font-family:ui-monospace,Consolas,monospace}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;
border:1px solid currentColor}.passed,.completed{color:var(--ok)}.failed,.error{color:var(--bad)}
.cancelled,.skipped,.waiting,.pending{color:var(--faint)}.running,.queued{color:var(--beacon)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:16px 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.card b{display:block;font-size:20px}table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600}pre{white-space:pre-wrap;word-break:break-word;margin:6px 0 0;
font-size:12px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px}
.shots{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
figure{margin:0;border:1px solid var(--line);border-radius:10px;overflow:hidden}
figure img{display:block;width:100%}figcaption{padding:6px 10px;font-size:12px;color:var(--muted)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:20px}@media(max-width:760px){.cols{grid-template-columns:1fr}}
.note{border-left:3px solid var(--beacon);padding:6px 12px;background:#fffbeb;margin:8px 0}
footer{margin-top:40px;font-size:12px;color:var(--faint)}
@media print{main{padding:0}figure,tr{break-inside:avoid}}
"""


def _e(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


def _ms(value: int | None) -> str:
    if value is None:
        return "—"
    if value < 1000:
        return f"{value} ms"
    if value < 60_000:
        return f"{value / 1000:.1f} s"
    return f"{value // 60_000}m {round((value % 60_000) / 1000)}s"


def _when(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S UTC") if value else "—"


def _status(value: str) -> str:
    return f'<span class="badge {_e(value)}">{_e(value)}</span>'


class ReportService:
    def __init__(self, db: AsyncSession, artifacts_root: Path, version: str) -> None:
        self._db = db
        self._root = artifacts_root
        self._version = version
        self._image_budget = MAX_TOTAL_IMAGE_BYTES

    async def build(self, execution: WorkflowExecution) -> str:
        project = await self._db.get(Project, execution.project_id)
        events = list(
            (
                await self._db.execute(
                    select(ExecutionEvent)
                    .where(ExecutionEvent.execution_id == execution.id)
                    .order_by(ExecutionEvent.seq)
                    .limit(5000)
                )
            ).scalars()
        )
        analysis = await self._db.scalar(
            select(FailureAnalysis)
            .where(FailureAnalysis.execution_id == execution.id)
            .order_by(FailureAnalysis.created_at.desc())
            .limit(1)
        )
        proposals = (
            list(
                (
                    await self._db.execute(
                        select(RepairProposal)
                        .where(RepairProposal.analysis_id == analysis.id)
                        .order_by(RepairProposal.created_at.desc())
                    )
                ).scalars()
            )
            if analysis
            else []
        )
        ai_ids = [str(e.data.get("ai_request_id")) for e in events if e.data.get("ai_request_id")]
        if analysis:
            ai_ids += list(analysis.ai_request_ids)
        for proposal in proposals:
            ai_ids += list(proposal.ai_request_ids)
        ai_requests = await self._ai_requests(execution.owner_id, ai_ids)

        test = execution.test_executions[0] if execution.test_executions else None
        snapshot = execution.snapshot
        title = test.test_name if test else str(snapshot.get("workflow_name", "Workflow"))
        version = test.version_number if test else snapshot.get("version", "?")
        parts = [
            self._header(execution, project, title, version, test),
            self._summary(execution, test),
            self._steps(execution, test) if test else self._nodes(execution),
            self._screenshots(execution, test),
            self._problems(events),
            self._analysis(analysis, proposals),
            self._ai(ai_requests),
        ]
        body = "\n".join(p for p in parts if p)
        generated = _when(utcnow())
        return (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
            "img-src data:; style-src 'unsafe-inline'\">"
            f"<title>{_e(title)} v{_e(version)} — TestPilot report</title>"
            f"<style>{CSS}</style></head><body><main>{body}"
            f"<footer>Generated by TestPilot {_e(self._version)} on {generated}. Self-contained "
            "report: screenshots are embedded, scripts are disabled, secret values are never "
            f'included. Run ID <span class="mono">{_e(execution.id)}</span>.</footer>'
            "</main></body></html>"
        )

    # ------------------------------------------------------------------ sections
    def _header(
        self,
        execution: WorkflowExecution,
        project: Project | None,
        title: str,
        version: Any,
        test: Any,
    ) -> str:
        kind = "Test run" if execution.kind == "test_run" else "Workflow run"
        where = (
            f'{_e(test.environment_name)} · <span class="mono">{_e(test.base_url)}</span> · '
            f"{_e(test.browser)} {_e(test.browser_version or '')}"
            if test
            else "Workflow"
        )
        isolation = (
            "Isolated browser worker"
            if execution.snapshot.get("isolated")
            else "Development mode (browser not isolated)"
        )
        error = (
            f'<p class="note"><b>Why it stopped:</b> {_e(execution.error_message)}</p>'
            if execution.error_message and execution.status != "passed"
            else ""
        )
        return (
            f'<p class="faint">{_e(kind)} · {_e(project.name if project else "")}</p>'
            f'<h1>{_e(title)} <span class="faint">v{_e(version)}</span> {_status(execution.status)}</h1>'
            f'<p class="muted">{where}<br>Started {_when(execution.started_at)} · '
            f"duration {_ms(execution.duration_ms)} · {_e(isolation)}</p>{error}"
        )

    def _summary(self, execution: WorkflowExecution, test: Any) -> str:
        if test:
            rows = test.steps
            counts = {
                s: sum(1 for r in rows if r.status == s) for s in ("passed", "failed", "skipped")
            }
            label = "steps"
        else:
            rows = execution.node_executions
            counts = {
                s: sum(1 for r in rows if r.status == s) for s in ("completed", "failed", "skipped")
            }
            label = "nodes"
        cards = "".join(
            f'<div class="card"><span class="muted">{_e(name.capitalize())} {label}</span>'
            f'<b class="{_e(name)}">{count}</b></div>'
            for name, count in counts.items()
        )
        cards += (
            f'<div class="card"><span class="muted">Total {label}</span><b>{len(rows)}</b></div>'
            f'<div class="card"><span class="muted">Duration</span><b>{_ms(execution.duration_ms)}</b></div>'
        )
        return f'<div class="grid">{cards}</div>'

    def _steps(self, execution: WorkflowExecution, test: Any) -> str:
        rows = []
        for step in test.steps:
            error = f"<pre>{_e(step.error_message)}</pre>" if step.error_message else ""
            rows.append(
                f'<tr><td class="mono">{step.index + 1}</td><td>{_e(step.description)}'
                f'<div class="faint mono">{_e(step.action)}</div>{error}</td>'
                f'<td>{_status(step.status)}</td><td class="mono">{_ms(step.duration_ms)}</td>'
                f'<td class="mono faint">{_e(step.url or "")}</td></tr>'
            )
        return (
            "<h2>Steps</h2><table><thead><tr><th>#</th><th>Step</th><th>Status</th>"
            f"<th>Duration</th><th>Page</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
        )

    def _nodes(self, execution: WorkflowExecution) -> str:
        rows = []
        for node in sorted(
            execution.node_executions, key=lambda n: (n.started_at is None, n.started_at)
        ):
            error = (
                f"<pre>{_e(node.error_code)}: {_e(node.error_message)}</pre>"
                if node.error_message
                else ""
            )
            rows.append(
                f'<tr><td>{_e(node.label)}<div class="faint mono">{_e(node.node_type)}</div>{error}</td>'
                f'<td>{_status(node.status)}</td><td class="mono">{_ms(node.duration_ms)}</td>'
                f'<td>{node.attempts}</td><td class="muted">{_e(node.summary or "")}</td></tr>'
            )
        return (
            "<h2>Nodes</h2><table><thead><tr><th>Node</th><th>Status</th><th>Duration</th>"
            f"<th>Attempts</th><th>Result</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
        )

    def _image(self, artifact: ExecutionArtifact) -> str | None:
        if artifact.size_bytes > MAX_IMAGE_BYTES or artifact.size_bytes > self._image_budget:
            return None
        path = (self._root / artifact.storage_path).resolve()
        if not path.is_relative_to(self._root) or not path.is_file():
            return None
        self._image_budget -= artifact.size_bytes
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{artifact.content_type};base64,{data}"

    def _screenshots(self, execution: WorkflowExecution, test: Any) -> str:
        frames = [
            a
            for a in execution.artifacts
            if a.kind == "screenshot" and a.content_type in ("image/jpeg", "image/png")
        ]
        if not frames:
            return ""
        figures = []
        for artifact in frames:
            uri = self._image(artifact)
            if uri is None:
                continue
            if test and artifact.step_index is not None and artifact.step_index < len(test.steps):
                step = test.steps[artifact.step_index]
                caption = f"After step {step.index + 1}: {step.description}"
            else:
                caption = f"{artifact.node_id or ''} {artifact.name}".strip()
            figures.append(
                f'<figure><img src="{uri}" alt="{_e(caption)}"><figcaption>{_e(caption)}</figcaption></figure>'
            )
        if not figures:
            return ""
        return f'<h2>Screenshots</h2><div class="shots">{"".join(figures)}</div>'

    def _problems(self, events: list[ExecutionEvent]) -> str:
        problems = [
            e
            for e in events
            if e.type in ("browser.console", "browser.network.failed", "browser.request.blocked")
            and e.level != "info"
        ]
        if not problems:
            return '<h2>Console and network</h2><p class="muted">No console errors, failed requests or blocked requests.</p>'
        items = "".join(
            f'<tr><td class="mono faint">{_e(e.type.split(".")[-1])}</td><td>{_e(e.message)}</td></tr>'
            for e in problems[:MAX_PROBLEMS]
        )
        more = (
            f'<p class="faint">…and {len(problems) - MAX_PROBLEMS} more.</p>'
            if len(problems) > MAX_PROBLEMS
            else ""
        )
        return f"<h2>Console and network</h2><table><tbody>{items}</tbody></table>{more}"

    def _analysis(self, analysis: FailureAnalysis | None, proposals: list[RepairProposal]) -> str:
        if analysis is None:
            return ""
        evidence = "".join(
            f'<tr><td class="mono">{_e(item.get("id"))}</td><td>{_e(item.get("title"))}'
            f"{'<pre>' + _e(item.get('detail')) + '</pre>' if item.get('kind') in ('error', 'step') else ''}"
            "</td></tr>"
            for item in analysis.evidence
        )
        result = analysis.result or {}
        hypotheses = "".join(
            f'<li>{_e(h.get("statement"))} <span class="faint">({_e(h.get("confidence"))} '
            f"confidence; {_e(', '.join(h.get('evidence_ids', [])))})</span></li>"
            for h in result.get("hypotheses", [])
        )
        ai = (
            f"<p><b>{_e(result.get('category', '').replace('_', ' '))}</b> · recommended: "
            f"{_e(result.get('recommended_action', '').replace('_', ' '))}</p>"
            f"<p>{_e(result.get('summary'))}</p><ul>{hypotheses}</ul>"
            if result
            else f'<p class="error">{_e(analysis.error_message)}</p>'
        )
        repair = ""
        if proposals:
            latest = proposals[0]
            changed = [row for row in latest.diff if row.get("kind") != "same"]
            repair = (
                f"<h3>Repair proposal — {_e(latest.status.replace('_', ' '))}</h3>"
                f"<p>{_e(latest.rationale)}</p>"
                + "".join(
                    f"<pre>{_e(row.get('kind'))}: {_e((row.get('before') or {}).get('description'))}"
                    f" → {_e((row.get('after') or {}).get('description'))} — {_e(row.get('reason'))}</pre>"
                    for row in changed
                )
            )
        return (
            '<h2>Failure analysis</h2><div class="cols"><div><h3>Verified evidence '
            '<span class="faint">(collected from the run)</span></h3>'
            f"<table><tbody>{evidence}</tbody></table></div><div><h3>AI explanation "
            f'<span class="faint">(hypotheses, not facts)</span></h3>{ai}</div></div>{repair}'
        )

    async def _ai_requests(self, owner_id: uuid.UUID, ids: list[str]) -> list[AIRequest]:
        unique: list[uuid.UUID] = []
        for value in ids:
            try:
                parsed = uuid.UUID(value)
            except ValueError:
                continue
            if parsed not in unique:
                unique.append(parsed)
        if not unique:
            return []
        rows = await self._db.execute(
            select(AIRequest)
            .where(AIRequest.id.in_(unique), AIRequest.owner_id == owner_id)
            .order_by(AIRequest.started_at)
        )
        return list(rows.scalars())

    def _ai(self, requests: list[AIRequest]) -> str:
        if not requests:
            return ""
        rows = "".join(
            f"<tr><td>{_e((r.task or r.origin).replace('_', ' '))}</td>"
            f'<td class="mono">{_e(r.actual_provider_type or r.requested_provider_type)}/'
            f"{_e(r.actual_model or r.requested_model)}</td><td>{_status(r.status)}</td>"
            f'<td class="mono">{_ms(r.latency_ms)}</td><td class="mono">{_e(r.total_tokens or "—")}</td>'
            f"<td>{'yes' if r.fallback_used else 'no'}</td></tr>"
            for r in requests
        )
        return (
            '<h2>AI used in this run</h2><p class="muted">External providers process these requests '
            "on their own servers. Requested and answering models are shown as reported.</p>"
            "<table><thead><tr><th>Task</th><th>Answered by</th><th>Status</th><th>Latency</th>"
            f"<th>Tokens</th><th>Fallback</th></tr></thead><tbody>{rows}</tbody></table>"
        )
