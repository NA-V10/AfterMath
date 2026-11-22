"""Authentication and role enforcement across the whole API (docs/SECURITY.md §3)."""

from __future__ import annotations

import re
import uuid

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text

from app.api.v1.router import PUBLIC_PATHS
from app.core.config import API_PREFIX
from app.core.security import issue_token
from app.database.session import Database
from tests.integration.conftest import TEST_PASSWORD

PARAM = re.compile(r"\{(\w+)\}")


def concrete(path: str) -> str:
    def value(m: re.Match[str]) -> str:
        name = m.group(1)
        if name == "record_id":
            return "1"
        if name.endswith("_id"):
            return str(uuid.uuid4())
        return "SUB-02"

    return PARAM.sub(value, path)


def api_routes(app: FastAPI) -> list[tuple[str, str]]:
    """Every operation the API publishes (from the OpenAPI document, so nothing is missed)."""
    out = []
    for path, ops in app.openapi()["paths"].items():
        for method in ops:
            if method in {"get", "post", "put", "patch", "delete"}:
                out.append((method.upper(), path.removeprefix(API_PREFIX)))
    return out


async def test_every_route_requires_a_token_except_health_and_login(
    app: FastAPI, clients: dict[str, AsyncClient]
) -> None:
    anon = clients["anon"]
    routes = api_routes(app)
    assert len(routes) > 40
    public, gated = [], []
    for method, path in routes:
        r = await anon.request(method, concrete(path), json={})
        if path in PUBLIC_PATHS:
            public.append(path)
            assert r.status_code != 401, (method, path)
        else:
            gated.append(path)
            assert r.status_code == 401, (method, path, r.status_code, r.text[:200])
            assert r.headers["www-authenticate"].startswith("Bearer")
            assert r.json()["type"].endswith("/unauthorized")
    assert sorted(set(public)) == sorted(PUBLIC_PATHS)


async def test_login_issues_a_working_token_and_failures_are_audited(
    clients: dict[str, AsyncClient],
) -> None:
    anon = clients["anon"]
    ok = await anon.post(
        "/auth/token", json={"username": "test-approver", "password": TEST_PASSWORD}
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["token_type"] == "bearer"
    assert body["user"] == {
        "username": "test-approver", "display_name": "Test Approver",
        "roles": ["approver"], "role": "approver",
    }  # fmt: skip
    me = await anon.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["governance"]["separation_of_duties"] is True

    wrong = await anon.post("/auth/token", json={"username": "test-approver", "password": "nope"})
    unknown = await anon.post("/auth/token", json={"username": "nobody", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]  # no username enumeration
    audit = await clients["test-admin"].get("/audit", params={"action": "auth.login_failed"})
    actors = {r["actor_id"] for r in audit.json()["items"]}
    assert {"test-approver", "nobody"} <= actors


async def test_repeated_failed_sign_ins_are_throttled(
    app: FastAPI, clients: dict[str, AsyncClient]
) -> None:
    anon = clients["anon"]
    body = {"username": "throttle-target", "password": "wrong-password"}
    codes = [(await anon.post("/auth/token", json=body)).status_code for _ in range(6)]
    assert codes == [401] * 5 + [429]
    r = await anon.post("/auth/token", json=body)
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) > 0
    assert r.json()["type"].endswith("/too-many-requests")
    # Another user from the same address is not affected.
    ok = await anon.post("/auth/token", json={"username": "test-viewer", "password": TEST_PASSWORD})
    assert ok.status_code == 200
    app.state.login_throttle.succeeded("throttle-target", "127.0.0.1")


async def test_api_responses_carry_security_headers(clients: dict[str, AsyncClient]) -> None:
    r = await clients["test-viewer"].get("/auth/me")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-security-policy"].startswith("default-src 'none'")
    assert r.headers["x-aftermath-environment"] == "SIMULATION"
    docs = await clients["anon"].get("/docs")
    assert "content-security-policy" not in docs.headers  # Swagger UI loads its own assets


async def test_bad_tokens_are_rejected(app: FastAPI, clients: dict[str, AsyncClient]) -> None:
    anon = clients["anon"]
    forged, _ = issue_token(
        "test-admin", ["admin"], secret="not-the-server-secret-0123456789abcd", ttl_minutes=5
    )
    for header in ("Bearer garbage", f"Bearer {forged}", "Basic dGVzdDp0ZXN0", "Bearer "):
        r = await anon.get("/infrastructure/health", headers={"Authorization": header})
        assert r.status_code == 401, header


async def test_deactivated_or_demoted_users_lose_access_immediately(
    clients: dict[str, AsyncClient], database: Database
) -> None:
    viewer = clients["test-viewer"]
    assert (await viewer.get("/auth/me")).status_code == 200
    async with database.sessionmaker() as s:
        await s.execute(
            text("UPDATE app_user SET is_active = false WHERE username = 'test-viewer'")
        )
        await s.commit()
    try:
        assert (await viewer.get("/auth/me")).status_code == 401  # same, still-valid token
    finally:
        async with database.sessionmaker() as s:
            await s.execute(
                text("UPDATE app_user SET is_active = true WHERE username = 'test-viewer'")
            )
            await s.commit()
    # Roles come from the database, not the token: a token claiming admin does not grant it.
    async with database.sessionmaker() as s:
        await s.execute(
            text("""UPDATE app_user SET roles = '["viewer"]' WHERE username = 'test-operator2'""")
        )
        await s.commit()
    try:
        r = await clients["test-operator2"].post(
            "/incidents", json={"source": "FREE_TEXT", "raw_report": "x" * 20}
        )
        assert r.status_code == 403
    finally:
        async with database.sessionmaker() as s:
            await s.execute(
                text("""UPDATE app_user SET roles = '["operator"]'
                        WHERE username = 'test-operator2'""")
            )
            await s.commit()


@pytest.mark.parametrize(
    ("user", "method", "path", "body", "expected"),
    [
        ("test-viewer", "GET", "/infrastructure/assets", None, 200),
        ("test-viewer", "POST", "/incidents", {"source": "FREE_TEXT", "raw_report": "x" * 20}, 403),
        ("test-operator", "POST", "/inventory",
         {"renewables": {"crew:CIVIL": 1}, "consumables": {"fuel_l": 1}, "reason": "try"}, 403),
        ("test-operator", "POST", "/operational-picture/reset", {"reason": "try"}, 403),
        ("test-viewer", "POST", "/simulations",
         {"scenario_key": "substation-riverside", "apply_to_picture": True}, 403),
        ("test-viewer", "POST", "/simulations", {"scenario_key": "substation-riverside"}, 201),
        ("test-viewer", "GET", "/audit/verify-chain", None, 200),
    ],
)  # fmt: skip
async def test_role_matrix(
    clients: dict[str, AsyncClient],
    user: str,
    method: str,
    path: str,
    body: dict[str, object] | None,
    expected: int,
) -> None:
    r = await clients[user].request(method, path, json=body)
    assert r.status_code == expected, r.text
    if expected == 403:
        assert r.json()["type"].endswith("/forbidden")
