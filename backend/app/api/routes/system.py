from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.dependencies import CurrentUser, SettingsDep
from app.schemas.system import SystemStatus
from app.services.system_service import system_status

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status", response_model=SystemStatus)
async def get_system_status(
    request: Request, _: CurrentUser, settings: SettingsDep
) -> SystemStatus:
    state = request.app.state
    return await system_status(
        settings=settings,
        engine=state.engine,
        redis=state.redis,
        rate_limiter_backend=state.rate_limiter.backend_name,
        started_at=state.started_at,
    )
