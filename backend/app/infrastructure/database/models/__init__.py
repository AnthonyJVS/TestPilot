"""Import every model here so Alembic autogenerate and metadata see all tables."""

from app.infrastructure.database.models.ai import (
    AICredential,
    AIModelConfiguration,
    AIProviderConnection,
    AIRequest,
    AIRoutingSettings,
    AITaskRoute,
)
from app.infrastructure.database.models.execution import (
    ExecutionArtifact,
    ExecutionEvent,
    ExecutionStep,
    TestExecution,
    WorkflowExecution,
)
from app.infrastructure.database.models.identity import AuditLog, AuthSession, RefreshToken, User
from app.infrastructure.database.models.testing import (
    EnvironmentVariable,
    Project,
    ProjectEnvironment,
    TestCase,
    TestPlanRecord,
    TestSuite,
    TestVersion,
)

__all__ = [
    "AICredential",
    "AIModelConfiguration",
    "AIProviderConnection",
    "AIRequest",
    "AIRoutingSettings",
    "AITaskRoute",
    "AuditLog",
    "AuthSession",
    "EnvironmentVariable",
    "ExecutionArtifact",
    "ExecutionEvent",
    "ExecutionStep",
    "Project",
    "ProjectEnvironment",
    "RefreshToken",
    "TestCase",
    "TestExecution",
    "TestPlanRecord",
    "TestSuite",
    "TestVersion",
    "User",
    "WorkflowExecution",
]
