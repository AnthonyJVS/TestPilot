from fastapi import APIRouter

from app.api.routes import ai, audit, auth, system

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(system.router)
api_router.include_router(audit.router)
api_router.include_router(ai.router)
