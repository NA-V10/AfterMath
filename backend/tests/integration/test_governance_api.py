"""Phase 5 governance over the API: approval bound to content, separation of duties, simulated
execution with revalidation (V-001…V-012), verification, idempotency, concurrency, reports and
audit integrity (docs/TESTING_STRATEGY.md P11-P14)."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database.session import Database
from tests.conftest import DATASET_DIR

RIVERSIDE = {
    "source": "STRUCTURED",
    "title": "Riverside substation failure",
    "incident_type": "POWER_FAILURE",
    "severity": "HIGH",
    "initiating_events": [{"kind": "ASSET_FAILURE", "asset_code": "SUB-02"}],
}
SEED_INVENTORY = json.loads((DATASET_DIR / "inventory.json").read_text(encoding="utf-8"))

Json = dict[str, Any]


@pytest.fixture(autouse=True)
async def restock(clients: dict[str, AsyncClient]) -> None:
    """Executions consume stock; give every test the seeded inventory as a fresh version."""
    r = await clients["test-admin"].post("/inventory", json={
        "renewables": SEED_INVENTORY["renewables"],
        "consumables": SEED_INVENTORY["consumables"],
        "reason": "test restock",
    })  # fmt: skip
    assert r.status_code == 201, r.text


async def planned(clients: dict[str, AsyncClient], requester: str = "test-operator") -> Json:
    c = clients[requester]
    incident = (await c.post("/incidents", json=RIVERSIDE)).json()
    r = await c.post("/recovery/strategies", json={"incident_id": incident["id"]})
    assert r.status_code == 201, r.text
    rnd: Json = r.json()
    assert all(s["status"] == "VALIDATED" for s in rnd["strategies"])
    assert all(s["requested_by"] == requester for s in rnd["strategies"])
    return rnd


def review(s: Json, **extra: Any) -> Json:
    return {"content_hash": s["content_hash"], "expected_version": s["version"], **extra}


async def strategy(c: AsyncClient, sid: str) -> Json:
    r = await c.get(f"/recovery/strategies/{sid}")
    assert r.status_code == 200
    return r.json()  # type: ignore[no-any-return]


async def approve(clients: dict[str, AsyncClient], s: Json, who: str = "test-approver") -> Json:
    r = await clients[who].post(
        f"/recovery/strategies/{s['id']}/approve", json=review(s, comment="Hospital first.")
    )
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


async def execute(c: AsyncClient, sid: str, key: str | None = None) -> Any:
    return await c.post(
        f"/recovery/strategies/{sid}/execute",
        headers={"Idempotency-Key": key or f"test-{uuid.uuid4()}"},
    )


async def test_approve_execute_verify_report(clients: dict[str, AsyncClient]) -> None:
    op, admin = clients["test-operator"], clients["test-admin"]
    rnd = await planned(clients)
    s = rnd["strategies"][0]
    decision = await approve(clients, s)
    assert decision["decision"] == "APPROVED"
    assert decision["content_hash"] == s["content_hash"]
    assert decision["actor_role"] == "approver"
    detail = await strategy(op, s["id"])
    assert detail["status"] == "APPROVED"
    assert [d["decision"] for d in detail["decisions"]] == ["APPROVED"]
    inv_before = (await op.get("/inventory")).json()

    key = f"exec-{uuid.uuid4()}"
    r = await execute(op, s["id"], key)
    assert r.status_code == 201, r.text
    ex = r.json()
    assert ex["status"] == "COMPLETED"
    assert ex["synthetic"] is True
    assert ex["revalidation"]["passed"] is True
    assert [x["rule"] for x in ex["revalidation"]["rules"]][-3:] == ["V-010", "V-011", "V-012"]
    v = ex["verification"]["result"]
    assert v["matches_expectation"] is True
    assert v["repaired_assets"] == ["SUB-02"]
    assert v["after"]["by_count"] > v["before"]["by_count"]
    assert ex["verification"]["verified_by"] == "agent:GUARDIAN"

    # Lifecycle consequences.
    assert (await strategy(op, s["id"]))["status"] == "VERIFIED"
    assert (await strategy(op, s["id"]))["execution_id"] == ex["id"]
    for other in rnd["strategies"][1:]:
        assert (await strategy(op, other["id"]))["status"] == "SUPERSEDED"
    incident = (await op.get(f"/incidents/{rnd['incident_id']}")).json()
    assert incident["status"] == "RECOVERED"
    inv_after = (await op.get("/inventory")).json()
    used = s["metrics"]["consumption"]
    if any(used.values()):
        assert inv_after["version"] == inv_before["version"] + 1
        assert inv_after["reason"].startswith("consumed by recovery execution")
        for k, n in used.items():
            assert inv_after["consumables"][k] == inv_before["consumables"][k] - n

    # Idempotent replay: same key, same execution, nothing runs twice.
    again = await execute(op, s["id"], key)
    assert again.status_code == 201
    assert again.json()["id"] == ex["id"]
    assert again.json()["replayed"] is True
    assert (await op.get(f"/recovery/executions/{ex['id']}/verification")).status_code == 200

    # P13: the executed run replays to the identical hash.
    replay = (await op.post(f"/simulations/{ex['simulation_run_id']}/replay")).json()
    assert replay["hash_matches"] is True
    assert (await op.get("/operational-picture")).json()["simulation_id"] == ex["simulation_run_id"]

    # Report (JSON + Markdown) comes from the stored records only.
    rr = await op.get(f"/reports/incidents/{rnd['incident_id']}")
    assert rr.status_code == 200, rr.text
    report = rr.json()
    assert report["notice"].startswith("SIMULATION ENVIRONMENT")
    assert report["execution"]["id"] == ex["id"]
    assert report["verification"]["matches_expectation"] is True
    assert [d["decision"] for d in report["decisions"]] == ["APPROVED"]
    actions = {a["action"] for a in report["audit_trail"]}
    assert {"strategies.generated", "strategy.approved", "strategy.executed",
            "recovery.verified"} <= actions  # fmt: skip
    md = await op.get(f"/reports/incidents/{rnd['incident_id']}", params={"format": "markdown"})
    assert md.headers["content-type"].startswith("text/markdown")
    assert md.text.startswith("> **SIMULATION ENVIRONMENT")
    assert md.text.rstrip().endswith("All data is synthetic.**")
    assert "## Verification (GUARDIAN)" in md.text
    assert (await admin.get("/audit/verify-chain")).json()["ok"] is True


async def test_separation_of_duties(clients: dict[str, AsyncClient]) -> None:
    rnd = await planned(clients, requester="test-admin")  # admin holds every role
    s = rnd["strategies"][0]
    r = await clients["test-admin"].post(f"/recovery/strategies/{s['id']}/approve", json=review(s))
    assert r.status_code == 403
    assert "Separation of duties" in r.json()["detail"]
    await approve(clients, s, who="test-approver2")


async def test_roles_for_decisions_and_execution(clients: dict[str, AsyncClient]) -> None:
    s = (await planned(clients))["strategies"][0]
    for who in ("test-operator", "test-viewer"):
        r = await clients[who].post(f"/recovery/strategies/{s['id']}/approve", json=review(s))
        assert r.status_code == 403, who
    await approve(clients, s)
    assert (await execute(clients["test-viewer"], s["id"])).status_code == 403
    assert (await strategy(clients["test-viewer"], s["id"]))["status"] == "APPROVED"


async def test_stale_reviews_are_refused(clients: dict[str, AsyncClient]) -> None:
    s = (await planned(clients))["strategies"][0]
    url = f"/recovery/strategies/{s['id']}/approve"
    appr = clients["test-approver"]
    r = await appr.post(url, json=review(s) | {"content_hash": "f" * 64})
    assert (r.status_code, r.json()["type"].rsplit("/", 1)[-1]) == (409, "content-hash-mismatch")
    r = await appr.post(url, json=review(s) | {"expected_version": s["version"] + 7})
    assert (r.status_code, r.json()["type"].rsplit("/", 1)[-1]) == (409, "version-conflict")
    assert (await strategy(appr, s["id"]))["status"] == "VALIDATED"


async def test_rejection_is_final_and_needs_a_comment(clients: dict[str, AsyncClient]) -> None:
    rnd = await planned(clients)
    appr, op = clients["test-approver"], clients["test-operator"]
    s = rnd["strategies"][0]
    short = await appr.post(f"/recovery/strategies/{s['id']}/reject", json=review(s, comment="x"))
    assert short.status_code == 422
    for each in rnd["strategies"]:
        r = await appr.post(
            f"/recovery/strategies/{each['id']}/reject", json=review(each, comment="Too slow.")
        )
        assert r.status_code == 201, r.text
    fresh = await strategy(appr, s["id"])
    assert fresh["status"] == "REJECTED"
    again = await appr.post(f"/recovery/strategies/{s['id']}/approve", json=review(fresh))
    assert again.status_code == 409
    assert (await execute(op, s["id"])).status_code == 409
    # Every option rejected: the incident needs a new plan.
    assert (await op.get(f"/incidents/{rnd['incident_id']}")).json()["status"] == "ANALYZED"


async def test_unapproved_strategies_never_execute(clients: dict[str, AsyncClient]) -> None:
    s = (await planned(clients))["strategies"][0]
    op = clients["test-operator"]
    r = await execute(op, s["id"])
    assert r.status_code == 409
    assert r.json()["type"].endswith("/invalid-state-transition")
    missing_key = await op.post(f"/recovery/strategies/{s['id']}/execute")
    assert missing_key.status_code == 422
    denied = (await clients["test-admin"].get(
        "/audit", params={"action": "strategy.execute_denied", "entity_id": s["id"]}
    )).json()["items"]  # fmt: skip
    assert denied
    assert denied[0]["actor_id"] == "test-operator"


async def test_only_one_strategy_per_incident_can_be_approved(
    clients: dict[str, AsyncClient],
) -> None:
    rnd = await planned(clients)
    await approve(clients, rnd["strategies"][0])
    second = rnd["strategies"][1]
    r = await clients["test-approver"].post(
        f"/recovery/strategies/{second['id']}/approve", json=review(second)
    )
    assert r.status_code == 409


async def test_tampering_after_approval_blocks_execution(
    clients: dict[str, AsyncClient], database: Database
) -> None:
    """P12: a content change after approval makes the strategy non-executable."""
    s = (await planned(clients))["strategies"][0]
    await approve(clients, s)
    async with database.sessionmaker() as session:
        await session.execute(
            text(
                "UPDATE recovery_action SET end_minutes = end_minutes - 30 WHERE strategy_id = :s"
            ),
            {"s": s["id"]},
        )
        await session.commit()
    r = await execute(clients["test-operator"], s["id"])
    assert r.status_code == 409
    assert r.json()["type"].endswith("/revalidation-failed")
    assert {"V-007", "V-009"} <= set(r.json()["failed_rules"])
    detail = await strategy(clients["test-operator"], s["id"])
    assert detail["status"] == "VALIDATION_FAILED"
    assert (await execute(clients["test-operator"], s["id"])).status_code == 409


async def test_inventory_shortage_after_approval_blocks_execution(
    clients: dict[str, AsyncClient],
) -> None:
    """V-010: approved against stock that no longer exists → not executable."""
    s = (await planned(clients))["strategies"][0]
    assert any(s["metrics"]["consumption"].values()), "scenario must consume something"
    await approve(clients, s)
    empty = dict.fromkeys(SEED_INVENTORY["consumables"], 0)
    r = await clients["test-admin"].post("/inventory", json={
        "renewables": SEED_INVENTORY["renewables"], "consumables": empty, "reason": "stock lost",
    })  # fmt: skip
    assert r.status_code == 201
    r = await execute(clients["test-operator"], s["id"])
    assert r.status_code == 409
    assert r.json()["failed_rules"] == ["V-010"]


async def test_concurrent_executions_run_exactly_once(clients: dict[str, AsyncClient]) -> None:
    rnd = await planned(clients)
    s = rnd["strategies"][0]
    await approve(clients, s)
    op = clients["test-operator"]
    results = await asyncio.gather(*(execute(op, s["id"]) for _ in range(3)))
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 409, 409], [r.text[:120] for r in results]
    report = (await op.get(f"/reports/incidents/{rnd['incident_id']}")).json()
    assert sum(a["action"] == "strategy.executed" for a in report["audit_trail"]) == 1


async def test_idempotency_key_cannot_be_reused_for_another_strategy(
    clients: dict[str, AsyncClient],
) -> None:
    a = (await planned(clients))["strategies"][0]
    b = (await planned(clients))["strategies"][0]
    await approve(clients, a)
    await approve(clients, b)
    key = f"shared-{uuid.uuid4()}"
    assert (await execute(clients["test-operator"], a["id"], key)).status_code == 201
    r = await execute(clients["test-operator"], b["id"], key)
    assert r.status_code == 409
    assert (await strategy(clients["test-operator"], b["id"]))["status"] == "APPROVED"


async def test_replanning_voids_an_approval(clients: dict[str, AsyncClient]) -> None:
    rnd = await planned(clients)
    s = rnd["strategies"][0]
    await approve(clients, s)
    r = await clients["test-operator"].post(
        "/recovery/strategies", json={"incident_id": rnd["incident_id"]}
    )
    assert r.status_code == 201
    assert (await strategy(clients["test-operator"], s["id"]))["status"] == "SUPERSEDED"
    assert (await execute(clients["test-operator"], s["id"])).status_code == 409


async def test_close_incident(clients: dict[str, AsyncClient]) -> None:
    rnd = await planned(clients)
    op = clients["test-operator"]
    url = f"/incidents/{rnd['incident_id']}/close"
    assert (
        await clients["test-viewer"].post(url, json={"reason": "drill over"})
    ).status_code == 403
    r = await op.post(url, json={"reason": "drill over"})
    assert r.status_code == 200
    assert r.json()["status"] == "CLOSED"
    statuses = [(await strategy(op, s["id"]))["status"] for s in rnd["strategies"]]
    assert statuses == ["SUPERSEDED"] * 3
    assert (await op.post(url, json={"reason": "again"})).status_code == 409


async def test_governance_records_are_append_only_and_the_chain_verifies(
    clients: dict[str, AsyncClient], database: Database
) -> None:
    """P14 (with the persistence tests): audit chain intact after the governance operations."""
    s = (await planned(clients))["strategies"][0]
    await approve(clients, s)
    ex = (await execute(clients["test-operator"], s["id"])).json()
    for statement in (
        "UPDATE approval_record SET comment = 'edited' WHERE strategy_id = :id",
        "DELETE FROM approval_record WHERE strategy_id = :id",
        "UPDATE recovery_execution SET status = 'FAILED' WHERE strategy_id = :id",
        "DELETE FROM recovery_verification WHERE execution_id = :ex",
    ):
        async with database.sessionmaker() as session:
            with pytest.raises(DBAPIError, match=r"is immutable"):
                await session.execute(text(statement), {"id": s["id"], "ex": ex["id"]})
            await session.rollback()
    chain = (await clients["test-viewer"].get("/audit/verify-chain")).json()
    assert chain["ok"] is True
    assert chain["first_broken_id"] is None
