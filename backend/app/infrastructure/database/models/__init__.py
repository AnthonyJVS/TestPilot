"""Import every model here so Alembic autogenerate and metadata see all tables."""

from app.infrastructure.database.models.ai import (
    AICredential,
    AIModelConfiguration,
    AIProviderConnection,
    AIRequest,
    AIRoutingSettings,
    AITaskRoute,
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
    "Project",
    "ProjectEnvironment",
    "RefreshToken",
    "TestCase",
    "TestPlanRecord",
    "TestSuite",
    "TestVersion",
    "User",
]
