"""Test plans: AI generation, manual drafts, validation and approval into immutable versions."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import AppError, ConflictError, NotFoundError
from app.domain.plan_validation import PlanIssue, has_errors, validate_plan
from app.domain.test_plan import TestPlan
from app.infrastructure.database.models import (
    AIRequest,
    Project,
    ProjectEnvironment,
    TestCase,
    TestPlanRecord,
    TestVersion,
)
from app.schemas.testing import RequirementAnalysis
from app.services.ai.orchestrator import AIOrchestrator
from app.services.ai.types import TaskCategory
from app.services.audit_service import AuditService
from app.services.context import RequestContext
from app.services.project_service import ProjectService
from app.services.test_generation import prompts
from app.services.test_generation.renderer import render


class ScenarioMissingError(AppError):
    code = "test.scenario_missing"
    http_status = 422
    message = "Describe the scenario before generating a plan."


class PlanHasErrorsError(AppError):
    code = "test.plan_invalid"
    http_status = 422
    message = "Fix the errors in the plan before approving it."


class PlanService:
    def __init__(
        self,
        db: AsyncSession,
        projects: ProjectService,
        orchestrator: AIOrchestrator | None = None,
    ) -> None:
        self._db = db
        self._projects = projects
        self._orchestrator = orchestrator
        self._audit = AuditService(db)

    # ----------------------------------------------------------------- context
    async def context(
        self, owner_id: uuid.UUID, case: TestCase, environment_id: uuid.UUID | None = None
    ) -> tuple[Project, ProjectEnvironment | None, dict[str, str]]:
        project = await self._projects.get_project(owner_id, case.suite.project_id)
        environment = None
        if environment_id is not None:
            environment = next((e for e in project.environments if e.id == environment_id), None)
            if environment is None:
                raise ConflictError("That environment does not belong to this project.")
        else:
            environment = next((e for e in project.environments if e.is_default), None)
        variables = (
            {v.name: ("secret" if v.is_secret else "env") for v in environment.variables}
            if environment
            else {}
        )
        return project, environment, variables

    def issues(
        self,
        plan: TestPlan,
        project: Project,
        environment: ProjectEnvironment | None,
        variables: dict[str, str],
    ) -> list[PlanIssue]:
        return validate_plan(
            plan,
            allowed_domains=list(project.allowed_domains),
            variables=variables,
            environment_name=environment.name if environment else None,
        )

    async def ai_requests(self, owner_id: uuid.UUID, ids: list[str]) -> list[AIRequest]:
        if not ids:
            return []
        uuids = [uuid.UUID(i) for i in ids]
        result = await self._db.execute(
            select(AIRequest).where(AIRequest.owner_id == owner_id, AIRequest.id.in_(uuids))
        )
        by_id = {r.id: r for r in result.scalars()}
        return [by_id[u] for u in uuids if u in by_id]

    # -------------------------------------------------------------- generation
    async def generate(
        self,
        owner_id: uuid.UUID,
        case_id: uuid.UUID,
        environment_id: uuid.UUID | None,
        ctx: RequestContext,
    ) -> TestPlanRecord:
        if self._orchestrator is None:  # pragma: no cover - wiring error
            raise RuntimeError("AI orchestrator not configured")
        case = await self._projects.get_case(owner_id, case_id)
        scenario = case.scenario.strip()
        if not scenario:
            raise ScenarioMissingError()
        project, _, variables = await self.context(owner_id, case, environment_id)
        shared: dict[str, Any] = {
            "base_url": project.base_url,
            "allowed_domains": list(project.allowed_domains),
            "variables": variables,
        }

        analysis = await self._orchestrator.run_structured(
            owner_id,
            TaskCategory.REQUIREMENT_ANALYSIS,
            system=prompts.ANALYSIS_SYSTEM,
            prompt=prompts.analysis_prompt(scenario, **shared),
            output_model=RequirementAnalysis,
            origin="test_generation",
        )
        planning = await self._orchestrator.run_structured(
            owner_id,
            TaskCategory.TEST_PLANNING,
            system=prompts.PLANNING_SYSTEM,
            prompt=prompts.planning_prompt(scenario, analysis.output, **shared),
            output_model=TestPlan,
            origin="test_generation",
            max_output_tokens=8192,
        )
        record = await self._new_revision(
            case,
            plan=planning.output,
            source="ai",
            analysis=analysis.output.model_dump(mode="json"),
            ai_request_ids=[str(analysis.record.id), str(planning.record.id)],
        )
        self._audit.record(
            "test.plan.generate",
            "success",
            ctx=ctx,
            user_id=owner_id,
            target_type="test_case",
            target_id=str(case.id),
            details={"revision": record.revision, "steps": len(planning.output.steps)},
        )
        await self._db.commit()
        return record

    # ------------------------------------------------------------ manual edits
    async def create_draft(
        self, owner_id: uuid.UUID, case_id: uuid.UUID, plan: TestPlan, *, based_on_ai: bool = False
    ) -> TestPlanRecord:
        case = await self._projects.get_case(owner_id, case_id)
        latest = case.plans[-1] if case.plans else None
        record = await self._new_revision(
            case,
            plan=plan,
            source="edited"
            if (based_on_ai or (latest is not None and latest.source != "manual"))
            else "manual",
            analysis=latest.analysis if latest else None,
            ai_request_ids=list(latest.ai_request_ids) if latest else [],
        )
        await self._db.commit()
        return record

    async def update_draft(
        self, owner_id: uuid.UUID, plan_id: uuid.UUID, plan: TestPlan
    ) -> TestPlanRecord:
        record = await self._projects.get_plan(owner_id, plan_id)
        if record.status != "draft":
            raise ConflictError(
                "Approved plans are immutable. Save your edits as a new draft.",
                code="test.plan_approved",
            )
        record.plan = plan.model_dump(mode="json")
        if record.source == "ai":
            record.source = "edited"
        await self._db.commit()
        return record

    # ---------------------------------------------------------------- approval
    async def approve(
        self, owner_id: uuid.UUID, plan_id: uuid.UUID, ctx: RequestContext
    ) -> TestVersion:
        record = await self._projects.get_plan(owner_id, plan_id)
        if record.status == "approved":
            raise ConflictError("This plan is already approved.", code="test.plan_approved")
        case = await self._projects.get_case(owner_id, record.test_case_id)
        plan = TestPlan.model_validate(record.plan)
        project, environment, variables = await self.context(owner_id, case)
        issues = self.issues(plan, project, environment, variables)
        if has_errors(issues):
            raise PlanHasErrorsError(details=[i.to_json() for i in issues if i.severity == "error"])

        number = max((v.version for v in case.versions), default=0) + 1
        code = render(plan, base_url=project.base_url, version=number)
        version = TestVersion(
            id=uuid.uuid4(),
            test_case_id=case.id,
            version=number,
            plan_id=record.id,
            plan=plan.model_dump(mode="json"),
            base_url=project.base_url,
            code_python=code.python,
            code_typescript=code.typescript,
            renderer_version=code.renderer_version,
            approved_by_id=owner_id,
        )
        self._db.add(version)
        record.status = "approved"
        await self._db.flush()
        case.current_version_id = version.id
        self._audit.record(
            "test.version.approve",
            "success",
            ctx=ctx,
            user_id=owner_id,
            target_type="test_case",
            target_id=str(case.id),
            details={"version": number, "plan_revision": record.revision},
        )
        await self._db.commit()
        return version

    async def get_version(self, owner_id: uuid.UUID, version_id: uuid.UUID) -> TestVersion:
        result = await self._db.execute(select(TestVersion).where(TestVersion.id == version_id))
        version = result.scalar_one_or_none()
        if version is None:
            raise NotFoundError("Version not found.")
        await self._projects.get_case(owner_id, version.test_case_id)  # ownership check (404)
        return version

    # ----------------------------------------------------------------- helpers
    async def _new_revision(
        self,
        case: TestCase,
        *,
        plan: TestPlan,
        source: str,
        analysis: dict[str, Any] | None,
        ai_request_ids: list[str],
    ) -> TestPlanRecord:
        revision = max((p.revision for p in case.plans), default=0) + 1
        record = TestPlanRecord(
            id=uuid.uuid4(),
            test_case_id=case.id,
            revision=revision,
            source=source,
            status="draft",
            plan=plan.model_dump(mode="json"),
            analysis=analysis,
            ai_request_ids=ai_request_ids,
            scenario_snapshot=case.scenario,
        )
        self._db.add(record)
        await self._db.flush()
        return record
