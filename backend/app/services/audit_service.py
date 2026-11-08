"""Audit logging. Entries join the caller's transaction; details are always redacted."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redaction import redact
from app.domain.exceptions import AppError
from app.infrastructure.database.models import AuditLog
from app.infrastructure.repositories.identity import AuditLogRepository
from app.services.context import RequestContext

Outcome = Literal["success", "failure", "denied"]


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = AuditLogRepository(session)

    def record(
        self,
        action: str,
        outcome: Outcome,
        *,
        ctx: RequestContext,
        user_id: uuid.UUID | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        details: dict[str, Any] | None = None,
        message: str | None = None,
    ) -> None:
        self._repo.add(
            AuditLog(
                user_id=user_id,
                action=action,
                outcome=outcome,
                target_type=target_type,
                target_id=target_id,
                ip_address=ctx.ip_address,
                user_agent=(ctx.user_agent or "")[:512] or None,
                request_id=ctx.request_id,
                details=redact(details or {}),
                message=message,
            )
        )

    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int, cursor: str | None
    ) -> tuple[list[AuditLog], str | None]:
        before = decode_cursor(cursor) if cursor else None
        rows = await self._repo.list_for_user(user_id, limit=limit + 1, before=before)
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id)
        return rows, next_cursor


class InvalidCursorError(AppError):
    code = "request.invalid_cursor"
    http_status = 400
    message = "The pagination cursor is invalid."


def encode_cursor(created_at: datetime, entry_id: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{entry_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        created, entry_id = base64.urlsafe_b64decode(padded).decode().split("|", 1)
        parsed = datetime.fromisoformat(created)
        if parsed.tzinfo is None:
            raise ValueError("cursor timestamp must be timezone-aware")
        return parsed, uuid.UUID(entry_id)
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidCursorError() from exc
