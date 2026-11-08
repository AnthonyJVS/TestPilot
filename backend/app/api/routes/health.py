"""Unauthenticated liveness/readiness probes for orchestrators (minimal information)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.schemas.system import LiveResponse, ReadyResponse
from app.services.system_service import check_database, check_redis

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    return LiveResponse()


@router.get("/ready", response_model=ReadyResponse, responses={503: {"model": ReadyResponse}})
async def ready(request: Request) -> JSONResponse:
    database = await check_database(request.app.state.engine)
    redis = await check_redis(request.app.state.redis)
    checks = {"database": database.status, "redis": redis.status}
    healthy = database.status == "ok" and redis.status != "error"
    body = ReadyResponse(status="ok" if healthy else "unavailable", checks=checks)
    return JSONResponse(status_code=200 if healthy else 503, content=body.model_dump())
