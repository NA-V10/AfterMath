from fastapi import APIRouter

from app.api.v1 import audit, infrastructure, system

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(infrastructure.router)
api_router.include_router(audit.router)
