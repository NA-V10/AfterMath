"""Password hashing and access tokens (docs/SECURITY.md §2-3, ADR-0014).

Passwords: scrypt from the standard library (memory-hard; no native dependency, which matters
under Windows Application Control). Stored as ``scrypt$n$r$p$salt_b64$hash_b64``.
Tokens: HS256 JWTs (PyJWT) carrying the username and roles, with issuer, audience and expiry.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
_DKLEN = 32
ISSUER = "aftermath"
AUDIENCE = "aftermath-api"
ALGORITHM = "HS256"


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=_DKLEN
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        dk = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(base64.b64decode(expected)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk, base64.b64decode(expected))


# A hash of a random password, so unknown usernames cost the same time as wrong passwords.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


@dataclass(frozen=True, slots=True)
class TokenClaims:
    username: str
    roles: tuple[str, ...]
    expires_at: datetime


class InvalidTokenError(Exception):
    pass


def issue_token(
    username: str, roles: list[str], *, secret: str, ttl_minutes: int, now: datetime | None = None
) -> tuple[str, datetime]:
    issued = now or datetime.now(UTC)
    expires = issued + timedelta(minutes=ttl_minutes)
    payload = {
        "sub": username,
        "roles": sorted(roles),
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM), expires


def decode_token(token: str, *, secret: str) -> TokenClaims:
    try:
        data = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],  # never accept "none" or another algorithm
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["sub", "exp", "iat", "iss", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from None
    roles = data.get("roles")
    if not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
        raise InvalidTokenError("malformed roles claim")
    return TokenClaims(
        username=str(data["sub"]),
        roles=tuple(roles),
        expires_at=datetime.fromtimestamp(int(data["exp"]), UTC),
    )
