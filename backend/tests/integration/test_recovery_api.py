"""Phase 4 API: inventory, strategy generation, comparison, validation, tamper detection."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.database.session import Database

STORM = {
    "source": "STRUCTURED",
    "title": "Severe storm, multiple sites",
    "incident_type": "COMBINED",
    "severity": "CRITICAL",
    "initiating_events": [
        {"kind": "ASSET_FAILURE", "asset_code": c}
        for c in ("SUB-02", "SUB-04", "PDN-01", "TEL-05", "WPS-02", "RD-04")
    ],
}


async def storm_round(client: AsyncClient) -> dict:  # type: ignore[type-arg]
    incident = (await client.post("/incidents", json=STORM)).json()
    r = await client.post("/recovery/strategies", json={"incident_id": incident["id"]})
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


async def test_inventory_is_seeded_and_versioned(client: AsyncClient) -> None:
    inv = (await client.get("/inventory")).json()
    assert inv["renewables"]["crew:ELECTRICAL"] >= 1
    assert inv["synthetic"] is True
    bad = await client.post(
        "/inventory",
        json={"renewables": {"crew:CIVIL": -1}, "consumables": {"x": 1}, "reason": "neg"},
    )
    assert bad.status_code == 422


async def test_generate_three_validated_strategies_with_baseline(client: AsyncClient) -> None:
    rnd = await storm_round(client)
    policies = [s["policy"] for s in rnd["strategies"]]
    assert policies == ["CRITICAL_FIRST", "MAX_RESTORATION", "BALANCED"]
    assert all(s["status"] == "VALIDATED" for s in rnd["strategies"])
    assert all(r["passed"] for s in rnd["strategies"] for r in s["validation_report"]["rules"])
    recommended = [s for s in rnd["strategies"] if s["recommended"]]
    assert len(recommended) == 1
    assert recommended[0]["id"] == rnd["recommended_strategy_id"]
    assert recommended[0]["impact_hours"] == min(s["impact_hours"] for s in rnd["strategies"])
    assert all(s["impact_hours"] < rnd["baseline_impact_hours"] for s in rnd["strategies"])
    detail = rnd["strategies"][0]
    assert detail["actions"][0]["seq"] == 1
    assert detail["benefits"] or detail["limitations"]
    assert detail["identical_to"] == []  # the storm produces three different plans


async def test_replanning_supersedes_the_previous_round(client: AsyncClient) -> None:
    rnd = await storm_round(client)
    incident_id = rnd["incident_id"]
    again = (await client.post("/recovery/strategies", json={"incident_id": incident_id})).json()
    assert again["planning_round"] == rnd["planning_round"] + 1
    old = (await client.get(f"/recovery/strategies/{rnd['strategies'][0]['id']}")).json()
    assert old["status"] == "SUPERSEDED"
    assert old["recommended"] is False
    r = await client.post(f"/recovery/strategies/{old['id']}/validate")
    assert r.status_code == 409


async def test_tampered_strategy_fails_validation_and_stays_failed(
    client: AsyncClient, database: Database
) -> None:
    rnd = await storm_round(client)
    sid = rnd["strategies"][1]["id"]
    async with database.sessionmaker() as s:
        await s.execute(
            text("UPDATE recovery_action SET end_minutes = end_minutes - 60 "
                 "WHERE strategy_id = :sid AND seq = 1"), {"sid": sid},
        )  # fmt: skip
        await s.commit()
    report = (await client.post(f"/recovery/strategies/{sid}/validate")).json()
    assert report["passed"] is False
    assert {r["rule"] for r in report["rules"] if not r["passed"]} >= {"V-007", "V-008", "V-009"}
    detail = (await client.get(f"/recovery/strategies/{sid}")).json()
    assert detail["status"] == "VALIDATION_FAILED"
    terminal = await client.post(f"/recovery/strategies/{sid}/validate")
    assert terminal.status_code == 409
    audit = (await client.get("/audit", params={"action": "strategy.validation_failed"})).json()
    assert any(a["entity_id"] == sid for a in audit["items"])


async def test_compare_and_list(client: AsyncClient) -> None:
    rnd = await storm_round(client)
    cmp = (
        await client.get("/recovery/strategies/compare", params={"incident_id": rnd["incident_id"]})
    ).json()
    assert cmp["planning_round"] == rnd["planning_round"]
    listed = (
        await client.get("/recovery/strategies", params={"incident_id": rnd["incident_id"]})
    ).json()
    assert len(listed) == 3
    assert (
        await client.get(
            "/recovery/strategies/compare",
            params={"incident_id": "00000000-0000-0000-0000-000000000000"},
        )
    ).status_code == 404


async def test_planning_requires_initiating_events(client: AsyncClient) -> None:
    incident = (
        await client.post(
            "/incidents",
            json={"source": "FREE_TEXT", "raw_report": "Unclear sirens downtown tonight."},
        )
    ).json()
    r = await client.post("/recovery/strategies", json={"incident_id": incident["id"]})
    assert r.status_code == 409


@pytest.mark.parametrize("crews", [0])
async def test_no_crews_means_unschedulable_not_impossible(client: AsyncClient, crews: int) -> None:
    current = (await client.get("/inventory")).json()
    scarce = {k: (crews if k.startswith("crew:") else v) for k, v in current["renewables"].items()}
    await client.post(
        "/inventory",
        json={
            "renewables": scarce,
            "consumables": current["consumables"],
            "reason": "test: no crews",
        },
    )
    try:
        rnd = await storm_round(client)
        for s in rnd["strategies"]:
            assert s["status"] == "VALIDATED"
            assert [a for a in s["actions"] if a["action_type"] in ("REPAIR", "REPLACE")] == []
            assert {u["reason"] for u in s["unschedulable"]} >= {"INSUFFICIENT_RESOURCES"}
            assert any("Cannot schedule" in lim for lim in s["limitations"])
    finally:
        await client.post(
            "/inventory",
            json={
                "renewables": current["renewables"],
                "consumables": current["consumables"],
                "reason": "test: restore",
            },
        )
