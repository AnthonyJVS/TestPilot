"""Repositories for identity data. All queries are explicit about ownership."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.infrastructure.database.models import AuditLog, AuthSession, RefreshToken, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    def add(self, user: User) -> None:
        self._session.add(user)


class AuthSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, auth_session: AuthSession) -> None:
        self._session.add(auth_session)

    def add_refresh_token(self, token: RefreshToken) -> None:
        self._session.add(token)

    async def get_with_user(self, session_id: uuid.UUID) -> AuthSession | None:
        result = await self._session.execute(
            select(AuthSession)
            .options(selectinload(AuthSession.user))
            .where(AuthSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_refresh_token(self, token_hash: str) -> RefreshToken | None:
        result = await self._session.execute(
            select(RefreshToken)
            .options(selectinload(RefreshToken.session).selectinload(AuthSession.user))
            .where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def revoke(self, session_id: uuid.UUID, *, reason: str, at: datetime) -> None:
        await self._session.execute(
            update(AuthSession)
            .where(AuthSession.id == session_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=at, revoke_reason=reason)
        )


class AuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, entry: AuditLog) -> None:
        self._session.add(entry)

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        limit: int,
        before: tuple[datetime, uuid.UUID] | None = None,
    ) -> list[AuditLog]:
        stmt = select(AuditLog).where(AuditLog.user_id == user_id)
        if before is not None:
            created_at, entry_id = before
            stmt = stmt.where(
                (AuditLog.created_at < created_at)
                | ((AuditLog.created_at == created_at) & (AuditLog.id < entry_id))
            )
        stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
