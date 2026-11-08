"""Projects, environments, test data, suites and test cases. Every query is scoped to the owner."""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.crypto import SecretCipher
from app.domain.exceptions import AppError, ConflictError, NotFoundError
from app.domain.plan_validation import normalize_domain
from app.domain.test_plan import VARIABLE_NAME
from app.infrastructure.database.base import utcnow
from app.infrastructure.database.models import (
    EnvironmentVariable,
    Project,
    ProjectEnvironment,
    TestCase,
    TestPlanRecord,
    TestSuite,
)
from app.schemas.testing import (
    CaseCreate,
    CaseUpdate,
    EnvironmentCreate,
    EnvironmentUpdate,
    ProjectCreate,
    ProjectUpdate,
    SuiteCreate,
    SuiteUpdate,
)
from app.services.audit_service import AuditService
from app.services.context import RequestContext

_DOMAIN = re.compile(
    r"^(\*\.)?([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"
)
_VARIABLE = re.compile(f"^{VARIABLE_NAME}$")


class InvalidInputError(AppError):
    code = "request.invalid"
    http_status = 422


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise InvalidInputError("Enter a full URL starting with https:// or http://.")
    if parts.username or parts.password:
        raise InvalidInputError("Do not put credentials in the URL; use environment secrets.")
    return url.strip().rstrip("/")


def normalize_domains(domains: Sequence[str], base_url: str) -> list[str]:
    result: list[str] = []
    for raw in [urlsplit(base_url).hostname or "", *domains]:
        domain = normalize_domain(raw)
        if not domain:
            continue
        if not _DOMAIN.match(domain):
            raise InvalidInputError(
                f"'{raw}' is not a valid domain (use example.com or *.example.com)."
            )
        if domain not in result:
            result.append(domain)
    return result


def secret_aad(environment_id: uuid.UUID, name: str) -> str:
    return f"env_var:{environment_id}:{name}"


def case_status(case: TestCase) -> str:
    if case.current_version_id is not None:
        return "approved"
    return "planned" if case.plans else "draft"


class ProjectService:
    def __init__(self, db: AsyncSession, cipher: SecretCipher) -> None:
        self._db = db
        self._cipher = cipher
        self._audit = AuditService(db)

    # ---------------------------------------------------------------- projects
    async def list_projects(
        self, owner_id: uuid.UUID, query: str | None = None
    ) -> list[tuple[Project, int, int, int]]:
        stmt = (
            select(Project).where(Project.owner_id == owner_id).order_by(Project.updated_at.desc())
        )
        if query:
            stmt = stmt.where(func.lower(Project.name).contains(query.strip().lower()))
        projects = list((await self._db.execute(stmt)).scalars().all())
        if not projects:
            return []
        ids = [p.id for p in projects]
        suites = dict(
            (
                await self._db.execute(
                    select(TestSuite.project_id, func.count(TestSuite.id))
                    .where(TestSuite.project_id.in_(ids))
                    .group_by(TestSuite.project_id)
                )
            ).all()
        )
        cases = dict(
            (
                await self._db.execute(
                    select(TestSuite.project_id, func.count(TestCase.id))
                    .join(TestCase, TestCase.suite_id == TestSuite.id)
                    .where(TestSuite.project_id.in_(ids))
                    .group_by(TestSuite.project_id)
                )
            ).all()
        )
        approved = dict(
            (
                await self._db.execute(
                    select(TestSuite.project_id, func.count(TestCase.id))
                    .join(TestCase, TestCase.suite_id == TestSuite.id)
                    .where(TestSuite.project_id.in_(ids), TestCase.current_version_id.is_not(None))
                    .group_by(TestSuite.project_id)
                )
            ).all()
        )
        return [
            (p, suites.get(p.id, 0), cases.get(p.id, 0), approved.get(p.id, 0)) for p in projects
        ]

    async def get_project(self, owner_id: uuid.UUID, project_id: uuid.UUID) -> Project:
        result = await self._db.execute(
            select(Project)
            .options(selectinload(Project.environments).selectinload(ProjectEnvironment.variables))
            .where(Project.id == project_id, Project.owner_id == owner_id)
            .execution_options(populate_existing=True)
        )
        project = result.scalar_one_or_none()
        if project is None:
            raise NotFoundError("Project not found.")
        return project

    async def create_project(
        self, owner_id: uuid.UUID, data: ProjectCreate, ctx: RequestContext
    ) -> Project:
        base_url = normalize_url(data.base_url)
        project = Project(
            id=uuid.uuid4(),
            owner_id=owner_id,
            name=data.name,
            description=data.description.strip(),
            base_url=base_url,
            allowed_domains=normalize_domains(data.allowed_domains or [], base_url),
        )
        # Sensible starting structure: one environment using the project URL, one suite.
        project.environments = [ProjectEnvironment(name="default", is_default=True)]
        project.suites = [TestSuite(name="General")]
        self._db.add(project)
        await self._flush_unique("You already have a project with this name.")
        self._audit.record(
            "project.create",
            "success",
            ctx=ctx,
            user_id=owner_id,
            target_type="project",
            target_id=str(project.id),
            details={"name": project.name},
        )
        await self._db.commit()
        return await self.get_project(owner_id, project.id)

    async def update_project(
        self, owner_id: uuid.UUID, project_id: uuid.UUID, data: ProjectUpdate
    ) -> Project:
        project = await self.get_project(owner_id, project_id)
        if data.name is not None:
            project.name = " ".join(data.name.split())
        if data.description is not None:
            project.description = data.description.strip()
        if data.base_url is not None:
            project.base_url = normalize_url(data.base_url)
        if data.allowed_domains is not None or data.base_url is not None:
            domains = (
                data.allowed_domains
                if data.allowed_domains is not None
                else project.allowed_domains
            )
            project.allowed_domains = normalize_domains(domains, project.base_url)
        await self._flush_unique("You already have a project with this name.")
        await self._db.commit()
        return await self.get_project(owner_id, project_id)

    async def delete_project(
        self, owner_id: uuid.UUID, project_id: uuid.UUID, ctx: RequestContext
    ) -> None:
        project = await self.get_project(owner_id, project_id)
        await self._db.delete(project)
        self._audit.record(
            "project.delete",
            "success",
            ctx=ctx,
            user_id=owner_id,
            target_type="project",
            target_id=str(project_id),
            details={"name": project.name},
        )
        await self._db.commit()

    # ------------------------------------------------------------ environments
    async def get_environment(
        self, owner_id: uuid.UUID, environment_id: uuid.UUID
    ) -> ProjectEnvironment:
        result = await self._db.execute(
            select(ProjectEnvironment)
            .join(Project)
            .options(
                selectinload(ProjectEnvironment.variables), selectinload(ProjectEnvironment.project)
            )
            .where(ProjectEnvironment.id == environment_id, Project.owner_id == owner_id)
            .execution_options(populate_existing=True)
        )
        environment = result.scalar_one_or_none()
        if environment is None:
            raise NotFoundError("Environment not found.")
        return environment

    async def create_environment(
        self, owner_id: uuid.UUID, project_id: uuid.UUID, data: EnvironmentCreate
    ) -> Project:
        project = await self.get_project(owner_id, project_id)
        environment = ProjectEnvironment(
            project_id=project.id,
            name=data.name.strip(),
            base_url=normalize_url(data.base_url) if data.base_url else None,
            is_default=data.is_default,
        )
        if data.is_default:
            for other in project.environments:
                other.is_default = False
        self._db.add(environment)
        await self._flush_unique("This project already has an environment with this name.")
        await self._db.commit()
        return await self.get_project(owner_id, project_id)

    async def update_environment(
        self, owner_id: uuid.UUID, environment_id: uuid.UUID, data: EnvironmentUpdate
    ) -> Project:
        environment = await self.get_environment(owner_id, environment_id)
        if data.name is not None:
            environment.name = data.name.strip()
        if "base_url" in data.model_fields_set:
            environment.base_url = normalize_url(data.base_url) if data.base_url else None
        if data.is_default:
            project = await self.get_project(owner_id, environment.project_id)
            for other in project.environments:
                other.is_default = other.id == environment.id
        await self._flush_unique("This project already has an environment with this name.")
        await self._db.commit()
        return await self.get_project(owner_id, environment.project_id)

    async def delete_environment(self, owner_id: uuid.UUID, environment_id: uuid.UUID) -> Project:
        environment = await self.get_environment(owner_id, environment_id)
        if environment.is_default:
            raise ConflictError(
                "The default environment cannot be deleted. Make another one the default first.",
                code="project.default_environment",
            )
        project_id = environment.project_id
        await self._db.delete(environment)
        await self._db.commit()
        return await self.get_project(owner_id, project_id)

    async def set_variable(
        self,
        owner_id: uuid.UUID,
        environment_id: uuid.UUID,
        name: str,
        value: str,
        is_secret: bool,
        ctx: RequestContext,
    ) -> Project:
        if not _VARIABLE.match(name):
            raise InvalidInputError("Variable names use UPPER_SNAKE_CASE, e.g. LOGIN_EMAIL.")
        environment = await self.get_environment(owner_id, environment_id)
        variable = next((v for v in environment.variables if v.name == name), None)
        if variable is None:
            variable = EnvironmentVariable(
                environment_id=environment.id, name=name, is_secret=is_secret
            )
            self._db.add(variable)
        variable.is_secret = is_secret
        if is_secret:
            encrypted = self._cipher.encrypt(
                value, associated_data=secret_aad(environment.id, name)
            )
            variable.value = None
            variable.ciphertext, variable.nonce, variable.key_id = (
                encrypted.ciphertext,
                encrypted.nonce,
                encrypted.key_id,
            )
            self._audit.record(
                "project.secret.set",
                "success",
                ctx=ctx,
                user_id=owner_id,
                target_type="environment",
                target_id=str(environment.id),
                details={"name": name},
            )
        else:
            variable.value = value
            variable.ciphertext = variable.nonce = variable.key_id = None
        await self._db.commit()
        return await self.get_project(owner_id, environment.project_id)

    async def delete_variable(
        self, owner_id: uuid.UUID, environment_id: uuid.UUID, name: str, ctx: RequestContext
    ) -> Project:
        environment = await self.get_environment(owner_id, environment_id)
        variable = next((v for v in environment.variables if v.name == name), None)
        if variable is None:
            raise NotFoundError("Variable not found.")
        await self._db.delete(variable)
        if variable.is_secret:
            self._audit.record(
                "project.secret.delete",
                "success",
                ctx=ctx,
                user_id=owner_id,
                target_type="environment",
                target_id=str(environment.id),
                details={"name": name},
            )
        await self._db.commit()
        return await self.get_project(owner_id, environment.project_id)

    # ------------------------------------------------------------------ suites
    async def list_suites(self, owner_id: uuid.UUID, project_id: uuid.UUID) -> Sequence[TestSuite]:
        await self.get_project(owner_id, project_id)
        result = await self._db.execute(
            select(TestSuite)
            .options(
                selectinload(TestSuite.cases).selectinload(TestCase.plans),
                selectinload(TestSuite.cases).selectinload(TestCase.versions),
            )
            .where(TestSuite.project_id == project_id)
            .order_by(TestSuite.created_at)
            .execution_options(populate_existing=True)
        )
        return result.scalars().all()

    async def get_suite(self, owner_id: uuid.UUID, suite_id: uuid.UUID) -> TestSuite:
        result = await self._db.execute(
            select(TestSuite)
            .join(Project)
            .where(TestSuite.id == suite_id, Project.owner_id == owner_id)
        )
        suite = result.scalar_one_or_none()
        if suite is None:
            raise NotFoundError("Suite not found.")
        return suite

    async def create_suite(
        self, owner_id: uuid.UUID, project_id: uuid.UUID, data: SuiteCreate
    ) -> TestSuite:
        await self.get_project(owner_id, project_id)
        suite = TestSuite(
            project_id=project_id, name=data.name, description=data.description.strip()
        )
        self._db.add(suite)
        await self._flush_unique("This project already has a suite with this name.")
        await self._touch(project_id)
        await self._db.commit()
        return suite

    async def update_suite(
        self, owner_id: uuid.UUID, suite_id: uuid.UUID, data: SuiteUpdate
    ) -> TestSuite:
        suite = await self.get_suite(owner_id, suite_id)
        if data.name is not None:
            suite.name = " ".join(data.name.split())
        if data.description is not None:
            suite.description = data.description.strip()
        await self._flush_unique("This project already has a suite with this name.")
        await self._db.commit()
        return suite

    async def delete_suite(self, owner_id: uuid.UUID, suite_id: uuid.UUID) -> None:
        suite = await self.get_suite(owner_id, suite_id)
        await self._db.delete(suite)
        await self._db.commit()

    # ------------------------------------------------------------------- cases
    async def get_case(self, owner_id: uuid.UUID, case_id: uuid.UUID) -> TestCase:
        result = await self._db.execute(
            select(TestCase)
            .join(TestSuite)
            .join(Project)
            .options(
                selectinload(TestCase.plans),
                selectinload(TestCase.versions),
                selectinload(TestCase.suite),
            )
            .where(TestCase.id == case_id, Project.owner_id == owner_id)
            .execution_options(populate_existing=True)
        )
        case = result.scalar_one_or_none()
        if case is None:
            raise NotFoundError("Test not found.")
        return case

    async def list_cases(
        self,
        owner_id: uuid.UUID,
        project_id: uuid.UUID,
        *,
        query: str | None = None,
        status: str | None = None,
        suite_id: uuid.UUID | None = None,
    ) -> list[TestCase]:
        await self.get_project(owner_id, project_id)
        stmt = (
            select(TestCase)
            .join(TestSuite)
            .options(selectinload(TestCase.plans), selectinload(TestCase.versions))
            .where(TestSuite.project_id == project_id)
            .order_by(TestCase.updated_at.desc())
        )
        if suite_id is not None:
            stmt = stmt.where(TestCase.suite_id == suite_id)
        if query:
            needle = query.strip().lower()
            stmt = stmt.where(
                func.lower(TestCase.name).contains(needle)
                | func.lower(TestCase.scenario).contains(needle)
            )
        cases = list((await self._db.execute(stmt)).scalars().all())
        if status:
            cases = [c for c in cases if case_status(c) == status]
        return cases

    async def create_case(
        self, owner_id: uuid.UUID, project_id: uuid.UUID, data: CaseCreate
    ) -> TestCase:
        suite = await self.get_suite(owner_id, data.suite_id)
        if suite.project_id != project_id:
            raise NotFoundError("Suite not found.")
        case = TestCase(
            id=uuid.uuid4(), suite_id=suite.id, name=data.name, scenario=data.scenario.strip()
        )
        self._db.add(case)
        await self._touch(project_id)
        await self._db.commit()
        return await self.get_case(owner_id, case.id)

    async def update_case(
        self, owner_id: uuid.UUID, case_id: uuid.UUID, data: CaseUpdate
    ) -> TestCase:
        case = await self.get_case(owner_id, case_id)
        if data.name is not None:
            case.name = " ".join(data.name.split())
        if data.scenario is not None:
            case.scenario = data.scenario.strip()
        if data.suite_id is not None and data.suite_id != case.suite_id:
            target = await self.get_suite(owner_id, data.suite_id)
            if target.project_id != case.suite.project_id:
                raise InvalidInputError("Tests can only move between suites of the same project.")
            case.suite_id = target.id
        await self._touch(case.suite.project_id)
        await self._db.commit()
        return await self.get_case(owner_id, case_id)

    async def delete_case(self, owner_id: uuid.UUID, case_id: uuid.UUID) -> None:
        case = await self.get_case(owner_id, case_id)
        case.current_version_id = None  # break the circular reference before cascading
        await self._db.flush()
        await self._db.delete(case)
        await self._db.commit()

    async def get_plan(self, owner_id: uuid.UUID, plan_id: uuid.UUID) -> TestPlanRecord:
        result = await self._db.execute(
            select(TestPlanRecord)
            .join(TestCase)
            .join(TestSuite)
            .join(Project)
            .where(TestPlanRecord.id == plan_id, Project.owner_id == owner_id)
        )
        plan = result.scalar_one_or_none()
        if plan is None:
            raise NotFoundError("Plan not found.")
        return plan

    # ----------------------------------------------------------------- helpers
    async def _touch(self, project_id: uuid.UUID) -> None:
        project = await self._db.get(Project, project_id)
        if project is not None:
            project.updated_at = utcnow()

    async def _flush_unique(self, message: str) -> None:
        try:
            await self._db.flush()
        except IntegrityError as exc:
            await self._db.rollback()
            raise ConflictError(message, code="resource.name_taken") from exc
