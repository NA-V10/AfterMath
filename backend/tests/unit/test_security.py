"""Password hashing and access tokens."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import SecretStr

from app.core.config import DEV_JWT_SECRET, Settings
from app.core.security import (
    AUDIENCE,
    ISSUER,
    InvalidTokenError,
    decode_token,
    hash_password,
    issue_token,
    verify_password,
)

SECRET = "unit-test-secret-0123456789abcdef0123"


def test_password_hash_roundtrip_and_salting() -> None:
    h1, h2 = hash_password("correct horse battery"), hash_password("correct horse battery")
    assert h1 != h2  # random salt
    assert h1.startswith("scrypt$16384$8$1$")
    assert verify_password("correct horse battery", h1)
    assert not verify_password("correct horse batterY", h1)


@pytest.mark.parametrize("stored", ["", "plain", "bcrypt$x$y", "scrypt$a$b$c$d$e", "scrypt$1$2"])
def test_malformed_hashes_never_verify(stored: str) -> None:
    assert not verify_password("anything", stored)


def test_token_roundtrip() -> None:
    token, expires = issue_token("alice", ["approver", "viewer"], secret=SECRET, ttl_minutes=30)
    claims = decode_token(token, secret=SECRET)
    assert claims.username == "alice"
    assert claims.roles == ("approver", "viewer")
    assert abs((claims.expires_at - expires).total_seconds()) < 1


def test_expired_token_is_rejected() -> None:
    past = datetime.now(UTC) - timedelta(hours=2)
    token, _ = issue_token("alice", ["viewer"], secret=SECRET, ttl_minutes=30, now=past)
    with pytest.raises(InvalidTokenError):
        decode_token(token, secret=SECRET)


def test_wrong_secret_audience_issuer_and_alg_none_are_rejected() -> None:
    token, _ = issue_token("alice", ["admin"], secret=SECRET, ttl_minutes=30)
    with pytest.raises(InvalidTokenError):
        decode_token(token, secret="another-secret-0123456789abcdef01234")
    now = int(datetime.now(UTC).timestamp())
    base = {"sub": "alice", "roles": ["admin"], "iat": now, "exp": now + 600}
    for payload in (
        base | {"iss": ISSUER, "aud": "elsewhere"},
        base | {"iss": "x", "aud": AUDIENCE},
    ):
        with pytest.raises(InvalidTokenError):
            decode_token(jwt.encode(payload, SECRET, algorithm="HS256"), secret=SECRET)
    unsigned = jwt.encode(base | {"iss": ISSUER, "aud": AUDIENCE}, None, algorithm="none")
    with pytest.raises(InvalidTokenError):
        decode_token(unsigned, secret=SECRET)
    bad_roles = jwt.encode(base | {"iss": ISSUER, "aud": AUDIENCE, "roles": "admin"}, SECRET)
    with pytest.raises(InvalidTokenError):
        decode_token(bad_roles, secret=SECRET)


def test_production_refuses_placeholder_secrets() -> None:
    s = Settings(aftermath_env="production", jwt_secret=SecretStr(DEV_JWT_SECRET))
    problems = s.insecure_defaults()
    assert any("JWT_SECRET" in p for p in problems)
    assert any("DATABASE_URL" in p for p in problems)
    from app.main import create_app

    with pytest.raises(RuntimeError, match="Refusing to start in production"):
        create_app(s)
