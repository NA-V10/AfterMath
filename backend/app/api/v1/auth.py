from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import SessionDep
from app.api.identity import Viewer
from app.core.errors import TooManyRequestsError, UnauthorizedError
from app.core.logging import get_logger
from app.core.ratelimit import LoginThrottle
from app.schemas.governance import GovernanceConfig, LoginIn, MeOut, PrincipalOut, TokenOut
from app.services import auth as service

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger(__name__)


def _throttle(request: Request) -> LoginThrottle:
    throttle: LoginThrottle = request.app.state.login_throttle
    return throttle


@router.post(
    "/token", response_model=TokenOut, responses={429: {"description": "Too many failed attempts"}}
)
async def login(body: LoginIn, request: Request, session: SessionDep) -> TokenOut:
    """Exchange a username and password for a bearer token. Failures are audited; after 5
    failures in 15 minutes for one username from one address, sign-in is refused with 429."""
    throttle = _throttle(request)
    client = request.client.host if request.client else "unknown"
    wait = throttle.retry_after(body.username, client)
    if wait is not None:
        log.info("login_throttled", security=True, username=body.username[:64], client=client)
        raise TooManyRequestsError(
            f"Too many failed sign-ins. Try again in {wait} seconds.", retry_after=wait
        )
    try:
        issued = await service.login(
            session, request.app.state.settings, body.username, body.password
        )
    except UnauthorizedError:
        throttle.failed(body.username, client)
        raise
    throttle.succeeded(body.username, client)
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
