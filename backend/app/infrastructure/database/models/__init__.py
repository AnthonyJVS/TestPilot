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

__all__ = [
    "AICredential",
    "AIModelConfiguration",
    "AIProviderConnection",
    "AIRequest",
    "AIRoutingSettings",
    "AITaskRoute",
    "AuditLog",
    "AuthSession",
    "RefreshToken",
    "User",
]
