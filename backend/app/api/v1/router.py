from fastapi import APIRouter

from app.api.v1 import audit, incidents, infrastructure, simulations, system, workflows

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(infrastructure.router)
api_router.include_router(audit.router)
api_router.include_router(simulations.scenarios_router)
api_router.include_router(simulations.router)
api_router.include_router(simulations.picture_router)
api_router.include_router(incidents.router)
api_router.include_router(workflows.router)
