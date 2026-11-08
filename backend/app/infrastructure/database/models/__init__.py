"""Import every model here so Alembic autogenerate and metadata see all tables."""

from app.infrastructure.database.models.identity import AuditLog, AuthSession, RefreshToken, User

__all__ = ["AuditLog", "AuthSession", "RefreshToken", "User"]
