"""Failure analysis, repair proposals and their human approval (milestone 7).

Nothing here changes a test without a person: a proposal becomes a new immutable version only
through ``approve``, which re-validates and re-renders the plan like any manual approval.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.exceptions import AppError, ConflictError, NotFoundError
from app.domain.failure import FailureAnalysisOutput, RepairOutput
from app.domain.plan_validation import has_errors, validate_plan
from app.domain.test_plan import TestPlan
from app.infrastructure.database.base import utcnow
from app.infrastructure.database.models import (
    ExecutionEvent,
    FailureAnalysis,
    RepairProposal,
    TestCase,
    TestExecution,
    TestVersion,
    WorkflowExecution,
)
from app.services.ai.orchestrator import AIOrchestrator
from app.services.ai.router import TaskRouter
from app.services.ai.types import TaskCategory
from app.services.audit_service import AuditService
from app.services.context import RequestContext
from app.services.project_service import ProjectService
from app.services.quality import prompts
from app.services.quality.analysis import analyse, vision_supported
from app.services.quality.evidence import test_run_evidence
from app.services.quality.repair import RepairNotApplicableError, apply_diff, build_diff
from app.services.test_generation.plan_service import PlanService

MAX_SCREENSHOT_BYTES = 2_000_000


class AnalysisNotPossibleError(AppError):
    code = "analysis.not_possible"
    http_status = 409


class QualityService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        artifacts_root: Path,
        orchestrator: AIOrchestrator,
        router: TaskRouter,
        projects: ProjectService,
        plans: PlanService,
    ) -> None:
        self._db = db
        self._root = artifacts_root
        self._ai = orchestrator
        self._router = router
        self._projects = projects
        self._plans = plans
        self._audit = AuditService(db)

    # ------------------------------------------------------------------ analysis
    async def _execution(self, owner_id: uuid.UUID, execution_id: uuid.UUID) -> WorkflowExecution:
        execution = await self._db.scalar(
            select(WorkflowExecution)
            .options(
                selectinload(WorkflowExecution.test_executions).selectinload(TestExecution.steps),
                selectinload(WorkflowExecution.artifacts),
            )
            .where(WorkflowExecution.id == execution_id, WorkflowExecution.owner_id == owner_id)
        )
        if execution is None:
            raise NotFoundError("Run not found.")
        return execution

    async def analyse_run(
        self, owner_id: uuid.UUID, execution_id: uuid.UUID, ctx: RequestContext
    ) -> FailureAnalysis:
        execution = await self._execution(owner_id, execution_id)
        if execution.status not in ("failed", "error"):
            raise AnalysisNotPossibleError("Only failed runs can be analysed.")
        if execution.kind != "test_run" or not execution.test_executions:
            raise AnalysisNotPossibleError(
                "Workflow runs are analysed by a Failure Analyzer node inside the workflow."
            )
        test = execution.test_executions[0]
        failed = next((s for s in test.steps if s.status == "failed"), None)
        version = (
            await self._db.get(TestVersion, test.test_version_id) if test.test_version_id else None
        )
        plan = TestPlan.model_validate(version.plan) if version else None
        case = await self._db.get(TestCase, test.test_case_id) if test.test_case_id else None
        events = list(
            (
                await self._db.execute(
                    select(ExecutionEvent)
                    .where(ExecutionEvent.execution_id == execution.id)
                    .order_by(ExecutionEvent.seq)
                    .limit(2000)
                )
            ).scalars()
        )
        history: list[tuple[str, Any]] = []
        if test.test_version_id is not None:
            rows = await self._db.execute(
                select(WorkflowExecution.status, WorkflowExecution.created_at)
                .join(TestExecution, TestExecution.execution_id == WorkflowExecution.id)
                .where(
                    TestExecution.test_version_id == test.test_version_id,
                    WorkflowExecution.id != execution.id,
                    WorkflowExecution.created_at < execution.created_at,
                    WorkflowExecution.status.in_(("passed", "failed", "error")),
                )
                .order_by(WorkflowExecution.created_at.desc())
                .limit(20)
            )
            history = [(status, created) for status, created in rows.all()]
        evidence = test_run_evidence(
            test=test,
            plan=plan,
            failed=failed,
            error_code=execution.error_code,
            error_message=execution.error_message,
            events=events,
            history=history,
        )
        image = None
        if failed is not None and await vision_supported(
            self._router, owner_id, TaskCategory.FAILURE_ANALYSIS
        ):
            image = self._screenshot(execution, failed.index)
        record = FailureAnalysis(
            owner_id=owner_id,
            execution_id=execution.id,
            test_case_id=test.test_case_id,
            test_version_id=test.test_version_id,
            failed_step_index=failed.index if failed else None,
            status="failed",
            evidence=evidence,
            used_screenshot=image is not None,
            created_at=utcnow(),
        )
        try:
            output, request_id = await analyse(
                self._ai,
                owner_id,
                evidence=evidence,
                scenario=case.scenario if case else "",
                image=image,
            )
        except AppError as exc:
            record.error_code, record.error_message = exc.code, exc.message
            self._db.add(record)
            await self._db.commit()
            raise
        record.status = "completed"
        record.result = output.model_dump(mode="json")
        record.ai_request_ids = [request_id]
        self._db.add(record)
        self._audit.record(
            "test.failure.analyse",
            "success",
            ctx=ctx,
            user_id=owner_id,
            target_type="execution",
            target_id=str(execution.id),
            details={"category": output.category},
        )
        await self._db.commit()
        return record

    def _screenshot(self, execution: WorkflowExecution, step_index: int) -> bytes | None:
        shots = [
            a
            for a in execution.artifacts
            if a.kind == "screenshot"
            and a.content_type == "image/jpeg"
            and a.step_index == step_index
        ]
        if not shots:
            return None
        path = (self._root / shots[-1].storage_path).resolve()
        if not path.is_relative_to(self._root) or not path.is_file():
            return None
        if path.stat().st_size > MAX_SCREENSHOT_BYTES:
            return None
        return path.read_bytes()

    async def latest(
        self, owner_id: uuid.UUID, execution_id: uuid.UUID
    ) -> tuple[FailureAnalysis | None, Sequence[RepairProposal]]:
        await self._execution(owner_id, execution_id)
        analysis = await self._db.scalar(
            select(FailureAnalysis)
            .where(
                FailureAnalysis.execution_id == execution_id, FailureAnalysis.owner_id == owner_id
            )
            .order_by(FailureAnalysis.created_at.desc())
            .limit(1)
        )
        if analysis is None:
            return None, []
        proposals = (
            (
                await self._db.execute(
                    select(RepairProposal)
                    .where(RepairProposal.analysis_id == analysis.id)
                    .order_by(RepairProposal.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return analysis, proposals

    # ------------------------------------------------------------------ repair
    async def _analysis(self, owner_id: uuid.UUID, analysis_id: uuid.UUID) -> FailureAnalysis:
        analysis = await self._db.scalar(
            select(FailureAnalysis).where(
                FailureAnalysis.id == analysis_id, FailureAnalysis.owner_id == owner_id
            )
        )
        if analysis is None:
            raise NotFoundError("Analysis not found.")
        return analysis

    async def propose_repair(
        self, owner_id: uuid.UUID, analysis_id: uuid.UUID, ctx: RequestContext
    ) -> RepairProposal:
        analysis = await self._analysis(owner_id, analysis_id)
        if analysis.status != "completed" or analysis.result is None:
            raise AnalysisNotPossibleError("Analyse the failure first.")
        if analysis.test_case_id is None or analysis.test_version_id is None:
            raise AnalysisNotPossibleError("The test or its version no longer exists.")
        version = await self._db.get(TestVersion, analysis.test_version_id)
        case = await self._projects.get_case(owner_id, analysis.test_case_id)
        if version is None:
            raise AnalysisNotPossibleError("The test version no longer exists.")
        plan = TestPlan.model_validate(version.plan)
        result = await self._ai.run_structured(
            owner_id,
            TaskCategory.TEST_REPAIR,
            system=prompts.REPAIR_SYSTEM,
            prompt=prompts.repair_prompt(
                scenario=case.scenario,
                plan=plan,
                failed_index=analysis.failed_step_index,
                evidence=analysis.evidence,
                analysis=FailureAnalysisOutput.model_validate(analysis.result),
            ),
            output_model=RepairOutput,
            origin="test_repair",
            max_output_tokens=4096,
        )
        output = result.output
        proposal = RepairProposal(
            owner_id=owner_id,
            analysis_id=analysis.id,
            test_case_id=case.id,
            base_version_id=version.id,
            status="no_change",
            verdict=output.verdict,
            rationale=output.rationale,
            changes=[c.model_dump(mode="json", exclude_none=True) for c in output.changes],
            diff=[],
            issues=[],
            ai_request_ids=[str(result.record.id)],
            created_at=utcnow(),
        )
        if output.verdict == "fix_test":
            try:
                proposal.diff = build_diff(plan, output.changes)
                candidate = apply_diff(plan, proposal.diff)
            except (RepairNotApplicableError, ValidationError) as exc:
                proposal.status = "invalid"
                proposal.issues = [
                    {
                        "severity": "error",
                        "code": "repair.not_applicable",
                        "message": str(exc)[:500],
                    }
                ]
            else:
                project, environment, variables = await self._plans.context(owner_id, case)
                issues = validate_plan(
                    candidate,
                    allowed_domains=list(project.allowed_domains),
                    variables=variables,
                    environment_name=environment.name if environment else None,
                )
                proposal.issues = [i.to_json() for i in issues]
                proposal.proposed_plan = candidate.model_dump(mode="json")
                proposal.status = "invalid" if has_errors(issues) else "proposed"
            await self._db.execute(
                update(RepairProposal)
                .where(RepairProposal.test_case_id == case.id, RepairProposal.status == "proposed")
                .values(status="superseded")
            )
        self._db.add(proposal)
        self._audit.record(
            "test.repair.propose",
            "success",
            ctx=ctx,
            user_id=owner_id,
            target_type="test_case",
            target_id=str(case.id),
            details={"verdict": output.verdict, "changes": len(output.changes)},
        )
        await self._db.commit()
        return proposal

    async def _proposal(self, owner_id: uuid.UUID, proposal_id: uuid.UUID) -> RepairProposal:
        proposal = await self._db.scalar(
            select(RepairProposal).where(
                RepairProposal.id == proposal_id, RepairProposal.owner_id == owner_id
            )
        )
        if proposal is None:
            raise NotFoundError("Repair proposal not found.")
        return proposal

    async def approve(
        self, owner_id: uuid.UUID, proposal_id: uuid.UUID, ctx: RequestContext
    ) -> tuple[RepairProposal, TestVersion]:
        proposal = await self._proposal(owner_id, proposal_id)
        if proposal.status != "proposed" or proposal.proposed_plan is None:
            raise ConflictError(
                "Only an open, valid proposal can be approved.", code="repair.closed"
            )
        case = await self._projects.get_case(owner_id, proposal.test_case_id)
        if case.current_version_id != proposal.base_version_id:
            proposal.status = "superseded"
            await self._db.commit()
            raise ConflictError(
                "The test changed since this proposal was made. Analyse a new run.",
                code="repair.stale",
            )
        plan = TestPlan.model_validate(proposal.proposed_plan)
        record = await self._plans.create_draft(owner_id, case.id, plan, based_on_ai=True)
        record.source = "repair"
        record.ai_request_ids = list(proposal.ai_request_ids)
        await self._db.commit()
        version = await self._plans.approve(owner_id, record.id, ctx)
        proposal = await self._proposal(owner_id, proposal_id)
        proposal.status = "approved"
        proposal.resulting_version_id = version.id
        proposal.decided_by_id = owner_id
        proposal.decided_at = utcnow()
        self._audit.record(
            "test.repair.approve",
            "success",
            ctx=ctx,
            user_id=owner_id,
            target_type="test_case",
            target_id=str(case.id),
            details={"proposal": str(proposal.id), "version": version.version},
        )
        await self._db.commit()
        return proposal, version

    async def reject(
        self, owner_id: uuid.UUID, proposal_id: uuid.UUID, note: str, ctx: RequestContext
    ) -> RepairProposal:
        proposal = await self._proposal(owner_id, proposal_id)
        if proposal.status not in ("proposed", "invalid"):
            raise ConflictError("This proposal is already closed.", code="repair.closed")
        proposal.status = "rejected"
        proposal.decision_note = note[:1000] or None
        proposal.decided_by_id = owner_id
        proposal.decided_at = utcnow()
        self._audit.record(
            "test.repair.reject",
            "success",
            ctx=ctx,
            user_id=owner_id,
            target_type="test_case",
            target_id=str(proposal.test_case_id),
            details={"proposal": str(proposal.id)},
        )
        await self._db.commit()
        return proposal

    async def rollback(
        self, owner_id: uuid.UUID, version_id: uuid.UUID, ctx: RequestContext
    ) -> TestVersion:
        """Make an earlier approved version current again. Versions stay immutable."""
        version = await self._plans.get_version(owner_id, version_id)
        case = await self._projects.get_case(owner_id, version.test_case_id)
        if case.current_version_id == version.id:
            raise ConflictError("This version is already current.", code="test.version_current")
        previous = next((v.version for v in case.versions if v.id == case.current_version_id), None)
        case.current_version_id = version.id
        await self._db.execute(
            update(RepairProposal)
            .where(RepairProposal.test_case_id == case.id, RepairProposal.status == "proposed")
            .values(status="superseded")
        )
        self._audit.record(
            "test.version.rollback",
            "success",
            ctx=ctx,
            user_id=owner_id,
            target_type="test_case",
            target_id=str(case.id),
            details={"from_version": previous, "to_version": version.version},
        )
        await self._db.commit()
        return version
