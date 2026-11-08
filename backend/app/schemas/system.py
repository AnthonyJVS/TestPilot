from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

CheckStatus = Literal["ok", "error", "not_configured"]


class LiveResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadyResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: dict[str, CheckStatus]


class DependencyStatus(BaseModel):
    status: CheckStatus
    latency_ms: float | None = None
    detail: str | None = None


class DatabaseStatus(DependencyStatus):
    dialect: str
    migration_revision: str | None = None


class SystemStatus(BaseModel):
    app_name: str
    version: str
    environment: str
    server_time: datetime
    uptime_seconds: float
    database: DatabaseStatus
    redis: DependencyStatus
    rate_limiter_backend: str
    registration_enabled: bool
