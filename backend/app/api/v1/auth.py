from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import SessionDep
from app.api.identity import Viewer
from app.schemas.governance import GovernanceConfig, LoginIn, MeOut, PrincipalOut, TokenOut
from app.services import auth as service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=TokenOut)
async def login(body: LoginIn, request: Request, session: SessionDep) -> TokenOut:
    """Exchange a username and password for a bearer token. Failures are audited."""
    issued = await service.login(session, request.app.state.settings, body.username, body.password)
    p = issued.principal
    return TokenOut(
        access_token=issued.access_token,
        expires_at=issued.expires_at,
        user=PrincipalOut(
            username=p.username, display_name=p.display_name, roles=list(p.roles), role=p.role
        ),
    )


@router.get("/me", response_model=MeOut)
async def me(request: Request, user: Viewer) -> MeOut:
    """The signed-in user, their roles and the governance settings that apply to them."""
    return MeOut(
        username=user.username,
        display_name=user.display_name,
        roles=list(user.roles),
        role=user.role,
        governance=GovernanceConfig(
            separation_of_duties=request.app.state.settings.governance_separation_of_duties
        ),
    )
