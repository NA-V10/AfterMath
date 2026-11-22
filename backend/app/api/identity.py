"""Who is acting (docs/SECURITY.md §3).

Every request except health checks and login carries `Authorization: Bearer <JWT>`. The token
proves the username; roles and the active flag are re-read from the database on every request,
so deactivating or demoting a user takes effect immediately rather than at token expiry.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request

from app.api.deps import SessionDep
from app.core.context import actor_var
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.logging import get_logger
from app.core.security import InvalidTokenError, decode_token
from app.governance.rules.policies import Role, has_role
from app.services.auth import Principal, get_active_user, principal_of

log = get_logger(__name__)


def bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise UnauthorizedError("Sign in to use AFTERMATH (missing bearer token).")
    return token.strip()


async def current_principal(request: Request, session: SessionDep) -> Principal:
    settings = request.app.state.settings
    try:
        claims = decode_token(bearer_token(request), secret=settings.jwt_secret.get_secret_value())
    except InvalidTokenError:
        raise UnauthorizedError("Your session is invalid or has expired. Sign in again.") from None
    user = await get_active_user(session, claims.username)
    if user is None:
        raise UnauthorizedError("This account is unknown or deactivated.")
    principal = principal_of(user)
    actor_var.set(principal.username)
    return principal


def require(role: Role) -> Callable[..., Awaitable[Principal]]:
    async def dependency(
        request: Request, principal: Annotated[Principal, Depends(current_principal)]
    ) -> Principal:
        if not has_role(principal.roles, role):
            log.info(
                "access_denied", security=True, username=principal.username,
                needed=role.value, path=request.url.path,
            )  # fmt: skip
            raise ForbiddenError(f"This action needs the {role.value} role.")
        return principal

    dependency.__name__ = f"require_{role.value}"
    return dependency


Viewer = Annotated[Principal, Depends(require(Role.VIEWER))]
Operator = Annotated[Principal, Depends(require(Role.OPERATOR))]
Approver = Annotated[Principal, Depends(require(Role.APPROVER))]
Admin = Annotated[Principal, Depends(require(Role.ADMIN))]
