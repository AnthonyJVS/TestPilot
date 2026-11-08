"""Testing Workspace API: projects, environments, test data, suites, tests, plans and versions."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import Ctx, CurrentUser, DbSession
from app.api.dependencies.ai import Cipher, get_orchestrator
from app.domain.test_plan import TestPlan
from app.infrastructure.database.models import (
    Project,
    ProjectEnvironment,
    TestCase,
    TestPlanRecord,
    TestSuite,
    TestVersion,
)
from app.schemas.testing import (
    AIRequestSummaryOut,
    CaseCreate,
    CaseOut,
    CaseSummaryOut,
    CaseUpdate,
    EnvironmentCreate,
    EnvironmentOut,
    EnvironmentUpdate,
    PlanGenerate,
    PlanIssueOut,
    PlanOut,
    PlanSave,
    ProjectCreate,
    ProjectOut,
    ProjectSummaryOut,
    ProjectUpdate,
    RequirementAnalysis,
    SuiteCreate,
    SuiteOut,
    SuiteUpdate,
    VariableOut,
    VariableUpsert,
    VersionOut,
    VersionSummaryOut,
)
from app.services.ai.orchestrator import AIOrchestrator
from app.services.project_service import ProjectService, case_status
from app.services.test_generation.plan_service import PlanService

router = APIRouter(tags=["testing"])


def get_project_service(db: DbSession, cipher: Cipher) -> ProjectService:
    return ProjectService(db, cipher)


Projects = Annotated[ProjectService, Depends(get_project_service)]


def get_plan_service(
    db: DbSession,
    projects: Projects,
    orchestrator: Annotated[AIOrchestrator, Depends(get_orchestrator)],
) -> PlanService:
    return PlanService(db, projects, orchestrator)


Plans = Annotated[PlanService, Depends(get_plan_service)]


# ------------------------------------------------------------------ mappers


def _environment_out(env: ProjectEnvironment, project: Project) -> EnvironmentOut:
    return EnvironmentOut(
        id=env.id,
        name=env.name,
        base_url=env.base_url,
        effective_base_url=env.base_url or project.base_url,
        is_default=env.is_default,
        variables=[
            VariableOut(
                name=v.name,
                is_secret=v.is_secret,
                value=None if v.is_secret else v.value,
                has_value=bool(v.ciphertext) if v.is_secret else v.value is not None,
                updated_at=v.updated_at,
            )
            for v in env.variables
        ],
    )


def _project_out(project: Project) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        base_url=project.base_url,
        allowed_domains=list(project.allowed_domains),
        environments=[_environment_out(e, project) for e in project.environments],
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _current_version_number(case: TestCase) -> int | None:
    return next((v.version for v in case.versions if v.id == case.current_version_id), None)


def _case_summary(case: TestCase) -> CaseSummaryOut:
    return CaseSummaryOut(
        id=case.id,
        suite_id=case.suite_id,
        name=case.name,
        status=case_status(case),
        current_version=_current_version_number(case),
        updated_at=case.updated_at,
    )


def _suite_out(suite: TestSuite) -> SuiteOut:
    return SuiteOut(
        id=suite.id,
        name=suite.name,
        description=suite.description,
        cases=[_case_summary(c) for c in suite.cases],
    )


async def _plan_out(
    record: TestPlanRecord,
    case: TestCase,
    owner_id: uuid.UUID,
    plans: PlanService,
    environment_id: uuid.UUID | None = None,
) -> PlanOut:
    plan = TestPlan.model_validate(record.plan)
    project, environment, variables = await plans.context(owner_id, case, environment_id)
    requests = await plans.ai_requests(owner_id, list(record.ai_request_ids))
    return PlanOut(
        id=record.id,
        revision=record.revision,
        source=record.source,
        status=record.status,
        plan=plan,
        analysis=RequirementAnalysis.model_validate(record.analysis) if record.analysis else None,
        issues=[
            PlanIssueOut(**i.to_json()) for i in plans.issues(plan, project, environment, variables)
        ],
        environment_name=environment.name if environment else None,
        ai_requests=[
            AIRequestSummaryOut(
                id=r.id,
                task=r.task,
                status=r.status,
                requested_provider_type=r.requested_provider_type,
                requested_model=r.requested_model,
                actual_provider_type=r.actual_provider_type,
                actual_model=r.actual_model,
                latency_ms=r.latency_ms,
                total_tokens=r.total_tokens,
                fallback_used=r.fallback_used,
            )
            for r in requests
        ],
        scenario_snapshot=record.scenario_snapshot,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


async def _case_out(case: TestCase, owner_id: uuid.UUID, plans: PlanService) -> CaseOut:
    latest = case.plans[-1] if case.plans else None
    return CaseOut(
        id=case.id,
        project_id=case.suite.project_id,
        suite_id=case.suite_id,
        name=case.name,
        scenario=case.scenario,
        status=case_status(case),
        current_version_id=case.current_version_id,
        latest_plan=await _plan_out(latest, case, owner_id, plans) if latest else None,
        versions=[
            VersionSummaryOut(id=v.id, version=v.version, created_at=v.created_at)
            for v in case.versions
        ],
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def _version_out(version: TestVersion) -> VersionOut:
    return VersionOut(
        id=version.id,
        test_case_id=version.test_case_id,
        version=version.version,
        plan=TestPlan.model_validate(version.plan),
        base_url=version.base_url,
        code_python=version.code_python,
        code_typescript=version.code_typescript,
        renderer_version=version.renderer_version,
        created_at=version.created_at,
    )


# ----------------------------------------------------------------- projects


@router.get("/projects", response_model=list[ProjectSummaryOut])
async def list_projects(
    user: CurrentUser, projects: Projects, q: Annotated[str | None, Query(max_length=100)] = None
) -> list[ProjectSummaryOut]:
    return [
        ProjectSummaryOut(
            id=p.id,
            name=p.name,
            description=p.description,
            base_url=p.base_url,
            suite_count=suites,
            case_count=cases,
            approved_count=approved,
            updated_at=p.updated_at,
        )
        for p, suites, cases, approved in await projects.list_projects(user.id, q)
    ]


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate, user: CurrentUser, projects: Projects, ctx: Ctx
) -> ProjectOut:
    return _project_out(await projects.create_project(user.id, body, ctx))


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: uuid.UUID, user: CurrentUser, projects: Projects) -> ProjectOut:
    return _project_out(await projects.get_project(user.id, project_id))


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID, body: ProjectUpdate, user: CurrentUser, projects: Projects
) -> ProjectOut:
    return _project_out(await projects.update_project(user.id, project_id, body))


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID, user: CurrentUser, projects: Projects, ctx: Ctx
) -> Response:
    await projects.delete_project(user.id, project_id, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------- environments


@router.post("/projects/{project_id}/environments", response_model=ProjectOut, status_code=201)
async def create_environment(
    project_id: uuid.UUID, body: EnvironmentCreate, user: CurrentUser, projects: Projects
) -> ProjectOut:
    return _project_out(await projects.create_environment(user.id, project_id, body))


@router.patch("/environments/{environment_id}", response_model=ProjectOut)
async def update_environment(
    environment_id: uuid.UUID, body: EnvironmentUpdate, user: CurrentUser, projects: Projects
) -> ProjectOut:
    return _project_out(await projects.update_environment(user.id, environment_id, body))


@router.delete("/environments/{environment_id}", response_model=ProjectOut)
async def delete_environment(
    environment_id: uuid.UUID, user: CurrentUser, projects: Projects
) -> ProjectOut:
    return _project_out(await projects.delete_environment(user.id, environment_id))


@router.put("/environments/{environment_id}/variables/{name}", response_model=ProjectOut)
async def set_variable(
    environment_id: uuid.UUID,
    name: str,
    body: VariableUpsert,
    user: CurrentUser,
    projects: Projects,
    ctx: Ctx,
) -> ProjectOut:
    project = await projects.set_variable(
        user.id, environment_id, name, body.value, body.is_secret, ctx
    )
    return _project_out(project)


@router.delete("/environments/{environment_id}/variables/{name}", response_model=ProjectOut)
async def delete_variable(
    environment_id: uuid.UUID, name: str, user: CurrentUser, projects: Projects, ctx: Ctx
) -> ProjectOut:
    return _project_out(await projects.delete_variable(user.id, environment_id, name, ctx))


# ----------------------------------------------------------------- suites


@router.get("/projects/{project_id}/suites", response_model=list[SuiteOut])
async def list_suites(
    project_id: uuid.UUID, user: CurrentUser, projects: Projects
) -> list[SuiteOut]:
    return [_suite_out(s) for s in await projects.list_suites(user.id, project_id)]


@router.post("/projects/{project_id}/suites", response_model=SuiteOut, status_code=201)
async def create_suite(
    project_id: uuid.UUID, body: SuiteCreate, user: CurrentUser, projects: Projects
) -> SuiteOut:
    suite = await projects.create_suite(user.id, project_id, body)
    return SuiteOut(id=suite.id, name=suite.name, description=suite.description, cases=[])


@router.patch("/suites/{suite_id}", response_model=SuiteOut)
async def update_suite(
    suite_id: uuid.UUID, body: SuiteUpdate, user: CurrentUser, projects: Projects
) -> SuiteOut:
    suite = await projects.update_suite(user.id, suite_id, body)
    suites = await projects.list_suites(user.id, suite.project_id)
    return _suite_out(next(s for s in suites if s.id == suite.id))


@router.delete("/suites/{suite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_suite(suite_id: uuid.UUID, user: CurrentUser, projects: Projects) -> Response:
    await projects.delete_suite(user.id, suite_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ cases


@router.get("/projects/{project_id}/cases", response_model=list[CaseSummaryOut])
async def list_cases(
    project_id: uuid.UUID,
    user: CurrentUser,
    projects: Projects,
    q: Annotated[str | None, Query(max_length=100)] = None,
    status_filter: Annotated[
        Literal["draft", "planned", "approved"] | None, Query(alias="status")
    ] = None,
    suite_id: uuid.UUID | None = None,
) -> list[CaseSummaryOut]:
    cases = await projects.list_cases(
        user.id, project_id, query=q, status=status_filter, suite_id=suite_id
    )
    return [_case_summary(c) for c in cases]


@router.post("/projects/{project_id}/cases", response_model=CaseOut, status_code=201)
async def create_case(
    project_id: uuid.UUID, body: CaseCreate, user: CurrentUser, projects: Projects, plans: Plans
) -> CaseOut:
    return await _case_out(await projects.create_case(user.id, project_id, body), user.id, plans)


@router.get("/cases/{case_id}", response_model=CaseOut)
async def get_case(
    case_id: uuid.UUID, user: CurrentUser, projects: Projects, plans: Plans
) -> CaseOut:
    return await _case_out(await projects.get_case(user.id, case_id), user.id, plans)


@router.patch("/cases/{case_id}", response_model=CaseOut)
async def update_case(
    case_id: uuid.UUID, body: CaseUpdate, user: CurrentUser, projects: Projects, plans: Plans
) -> CaseOut:
    return await _case_out(await projects.update_case(user.id, case_id, body), user.id, plans)


@router.delete("/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_case(case_id: uuid.UUID, user: CurrentUser, projects: Projects) -> Response:
    await projects.delete_case(user.id, case_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------- plans


@router.post("/cases/{case_id}/plans/generate", response_model=CaseOut, status_code=201)
async def generate_plan(
    case_id: uuid.UUID,
    body: PlanGenerate,
    user: CurrentUser,
    projects: Projects,
    plans: Plans,
    ctx: Ctx,
) -> CaseOut:
    """Runs requirement analysis and test planning with the routed AI models (two AI calls)."""
    await plans.generate(user.id, case_id, body.environment_id, ctx)
    return await _case_out(await projects.get_case(user.id, case_id), user.id, plans)


@router.post("/cases/{case_id}/plans", response_model=CaseOut, status_code=201)
async def create_plan(
    case_id: uuid.UUID, body: PlanSave, user: CurrentUser, projects: Projects, plans: Plans
) -> CaseOut:
    """Saves a plan written or edited by the user as a new draft revision."""
    await plans.create_draft(user.id, case_id, body.plan)
    return await _case_out(await projects.get_case(user.id, case_id), user.id, plans)


@router.put("/plans/{plan_id}", response_model=CaseOut)
async def update_plan(
    plan_id: uuid.UUID, body: PlanSave, user: CurrentUser, projects: Projects, plans: Plans
) -> CaseOut:
    record = await plans.update_draft(user.id, plan_id, body.plan)
    return await _case_out(await projects.get_case(user.id, record.test_case_id), user.id, plans)


@router.post("/plans/{plan_id}/approve", response_model=VersionOut, status_code=201)
async def approve_plan(plan_id: uuid.UUID, user: CurrentUser, plans: Plans, ctx: Ctx) -> VersionOut:
    return _version_out(await plans.approve(user.id, plan_id, ctx))


@router.get("/versions/{version_id}", response_model=VersionOut)
async def get_version(version_id: uuid.UUID, user: CurrentUser, plans: Plans) -> VersionOut:
    return _version_out(await plans.get_version(user.id, version_id))
