from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.audit import AuditLogOut, AuditLogPage
from app.services.audit_service import AuditService

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=AuditLogPage)
async def list_audit_logs(
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> AuditLogPage:
    rows, next_cursor = await AuditService(db).list_for_user(user.id, limit=limit, cursor=cursor)
    return AuditLogPage(
        items=[AuditLogOut.model_validate(row) for row in rows], next_cursor=next_cursor
    )
