"""Users, login and token issuance (docs/SECURITY.md §3). Security events are audited."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import InvalidInputError, UnauthorizedError
from app.core.logging import get_logger
from app.core.security import DUMMY_HASH, hash_password, issue_token, verify_password
from app.database.models import ROLES, AppUser
from app.governance.rules.policies import highest
from app.services.audit import append_audit

log = get_logger(__name__)
MIN_PASSWORD_LENGTH = 12


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller, resolved from the database on every request."""

    username: str
    display_name: str
    roles: tuple[str, ...]

    @property
    def role(self) -> str:
        return highest(self.roles).value


@dataclass(frozen=True, slots=True)
class IssuedToken:
    access_token: str
    expires_at: datetime
    principal: Principal


def principal_of(user: AppUser) -> Principal:
    return Principal(user.username, user.display_name, tuple(user.roles))


async def get_active_user(session: AsyncSession, username: str) -> AppUser | None:
    user = await session.scalar(select(AppUser).where(AppUser.username == username))
    return user if user and user.is_active else None


async def login(
    session: AsyncSession, settings: Settings, username: str, password: str
) -> IssuedToken:
    user = await session.scalar(select(AppUser).where(AppUser.username == username))
    # Always run one scrypt verification so timing does not reveal which usernames exist.
    ok = verify_password(password, user.password_hash if user else DUMMY_HASH)
    if not (user and user.is_active and ok):
        log.info("login_failed", security=True, username=username[:64])
        await append_audit(
            session, actor_type="USER", actor_id=username[:64] or "(empty)",
            action="auth.login_failed", entity_type="app_user", entity_id=username[:64],
        )  # fmt: skip
        await session.commit()
        raise UnauthorizedError("Unknown user or wrong password.")
    token, expires = issue_token(
        user.username,
        list(user.roles),
        secret=settings.jwt_secret.get_secret_value(),
        ttl_minutes=settings.jwt_ttl_minutes,
    )
    log.info("login_succeeded", security=True, username=user.username)
    await append_audit(
        session, actor_type="USER", actor_id=user.username, action="auth.login",
        entity_type="app_user", entity_id=user.username, details={"roles": list(user.roles)},
    )  # fmt: skip
    await session.commit()
    return IssuedToken(token, expires, principal_of(user))


async def upsert_user(
    session: AsyncSession,
    *,
    username: str,
    display_name: str,
    password: str,
    roles: list[str],
    actor_id: str,
) -> AppUser:
    """Create a user, or reset an existing user's password, name and roles."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise InvalidInputError(f"Passwords need at least {MIN_PASSWORD_LENGTH} characters.")
    unknown = sorted(set(roles) - set(ROLES))
    if unknown or not roles:
        raise InvalidInputError(f"Roles must be a non-empty subset of {ROLES}; got {unknown}.")
    user = await session.scalar(select(AppUser).where(AppUser.username == username))
    action = "user.updated" if user else "user.created"
    if user is None:
        user = AppUser(username=username)
        session.add(user)
    user.display_name, user.roles, user.is_active = display_name, sorted(roles), True
    user.password_hash = hash_password(password)
    await session.flush()
    await append_audit(
        session, actor_type="SYSTEM", actor_id=actor_id, action=action, entity_type="app_user",
        entity_id=username, after={"roles": sorted(roles), "display_name": display_name},
    )  # fmt: skip
    await session.commit()
    return user
