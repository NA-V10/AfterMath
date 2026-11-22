from fastapi import APIRouter, Depends

from app.api.identity import require
from app.api.v1 import (
    audit,
    auth,
    incidents,
    infrastructure,
    recovery,
    reports,
    simulations,
    system,
    workflows,
)
from app.governance.rules.policies import Role

# Signed-in access for everything except health checks and login (docs/SECURITY.md §3).
# Routes that change state additionally require operator, approver or admin.
signed_in = [Depends(require(Role.VIEWER))]

api_router = APIRouter()
api_router.include_router(system.router)  # /health, /health/ready public; /system/status gated
api_router.include_router(auth.router)
api_router.include_router(infrastructure.router, dependencies=signed_in)
api_router.include_router(audit.router, dependencies=signed_in)
api_router.include_router(simulations.scenarios_router, dependencies=signed_in)
api_router.include_router(simulations.router, dependencies=signed_in)
api_router.include_router(simulations.picture_router, dependencies=signed_in)
api_router.include_router(incidents.router, dependencies=signed_in)
api_router.include_router(workflows.router, dependencies=signed_in)
api_router.include_router(recovery.router, dependencies=signed_in)
api_router.include_router(reports.router, dependencies=signed_in)

#: Paths that intentionally need no token (asserted by tests).
PUBLIC_PATHS = frozenset({"/health", "/health/ready", "/auth/token"})
