"""Phase 2 API: scenarios, simulations, operational picture, incidents, criticality."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database.session import Database


async def run(client: AsyncClient, **body: object) -> dict:  # type: ignore[type-arg]
    r = await client.post("/simulations", json=body)
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


async def test_scenarios_are_listed(client: AsyncClient) -> None:
    keys = [s["key"] for s in (await client.get("/scenarios")).json()]
    assert keys == ["power-telecom-combined", "river-flood", "substation-riverside"]
    assert (await client.get("/scenarios/nope")).status_code == 404


async def test_scenario_simulation_matches_engine_and_replays(client: AsyncClient) -> None:
    sim = await run(client, scenario_key="substation-riverside", label="golden")
    assert sim["status"] == "COMPLETED"
    assert sim["scenario_key"] == "substation-riverside"
    assert sim["final_metrics"]["affected_population"] == 176_000
    assert sim["failed_count"] == 12
    assert len(sim["result_hash"]) == 64

    events = (await client.get(f"/simulations/{sim['id']}/events")).json()
    assert events[0]["seq"] == 1
    assert events[-1]["kind"] == "HORIZON_REACHED"
    later = (await client.get(f"/simulations/{sim['id']}/events", params={"from_t": 100})).json()
    assert {e["t_minutes"] for e in later} >= {120, 240}
    assert min(e["t_minutes"] for e in later) >= 100

    replay = (await client.post(f"/simulations/{sim['id']}/replay")).json()
    assert replay["hash_matches"] is True
    assert replay["snapshot_matches"] is True

    again = await run(client, scenario_key="substation-riverside")
    assert again["result_hash"] == sim["result_hash"]


async def test_custom_events_and_validation(client: AsyncClient) -> None:
    sim = await run(
        client,
        initiating_events=[{"kind": "ASSET_FAILURE", "asset_code": "PDN-07", "t_minutes": 0}],
        horizon_minutes=120,
    )
    assert sim["horizon_minutes"] == 120
    state = {s["code"]: s["status"] for s in sim["final_state"]}
    assert state["HOS-01"] == "OPERATIONAL"  # still fed via PDN-02 (N-1)
    assert state["FIR-01"] == "ON_BACKUP"

    bad = [
        {"initiating_events": [{"kind": "ASSET_FAILURE", "asset_code": "XX-99"}]},
        {"initiating_events": [{"kind": "ASSET_FAILURE", "asset_code": "SUB-01", "t_minutes": 999}],
         "horizon_minutes": 60},
        {"scenario_key": "river-flood",
         "initiating_events": [{"kind": "ASSET_FAILURE", "asset_code": "SUB-01"}]},
        {},
        {"initiating_events": [{"kind": "METEOR", "asset_code": "SUB-01"}]},
    ]  # fmt: skip
    for body in bad:
        r = await client.post("/simulations", json=body)
        assert r.status_code == 422, (body, r.text)
        assert r.headers["content-type"].startswith("application/problem+json")


async def test_compare_two_runs(client: AsyncClient) -> None:
    a = await run(client, scenario_key="substation-riverside")
    b = await run(client, scenario_key="river-flood")
    cmp = (await client.get("/simulations/compare", params={"ids": f"{a['id']},{b['id']}"})).json()
    assert set(cmp["failed_only_in_b"]) == {"BR-01", "RD-03", "FUL-02"}
    assert cmp["failed_only_in_a"] == []
    assert cmp["impact_delta"] > 0
    bad = await client.get("/simulations/compare", params={"ids": a["id"]})
    assert bad.status_code == 422


async def test_listing_and_unknown_run(client: AsyncClient) -> None:
    await run(client, scenario_key="river-flood")
    page = (await client.get("/simulations", params={"limit": 2})).json()
    assert len(page["items"]) == 2
    assert page["next_cursor"]
    nxt = (
        await client.get("/simulations", params={"limit": 2, "cursor": page["next_cursor"]})
    ).json()
    assert {i["id"] for i in nxt["items"]}.isdisjoint({i["id"] for i in page["items"]})
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/simulations/{missing}")).status_code == 404


async def test_operational_picture_apply_and_reset(client: AsyncClient) -> None:
    sim = await run(client, scenario_key="power-telecom-combined", apply_to_picture=True)
    pic = (await client.get("/operational-picture")).json()
    assert pic["source"] == "simulation"
    assert pic["simulation_id"] == sim["id"]
    assert {s["code"]: s["status"] for s in pic["states"]}["EOC-01"] == "FAILED"

    reset = (await client.post("/operational-picture/reset", json={"reason": "test"})).json()
    assert reset["source"] == "baseline"
    assert {s["status"] for s in reset["states"]} == {"OPERATIONAL"}
    assert reset["metrics"]["impact_score"] == 0

    applied = (await client.post(f"/operational-picture/apply/{sim['id']}")).json()
    assert applied["source"] == "simulation"
    await client.post("/operational-picture/reset", json={})

    audit = (await client.get("/audit", params={"action": "picture.reset"})).json()
    assert len(audit["items"]) >= 2


async def test_simulation_records_are_immutable(client: AsyncClient, database: Database) -> None:
    await run(client, scenario_key="river-flood")
    async with database.sessionmaker() as s:
        for stmt in (
            "UPDATE simulation_run SET label = 'tampered'",
            "DELETE FROM simulation_event",
            "DELETE FROM operational_picture_change",
        ):
            with pytest.raises(DBAPIError, match="immutable"):
                await s.execute(text(stmt))
            await s.rollback()


async def test_structured_incident_can_be_simulated(client: AsyncClient) -> None:
    r = await client.post(
        "/incidents",
        json={
            "source": "STRUCTURED",
            "title": "Transformer fire at Riverside",
            "incident_type": "POWER_FAILURE",
            "severity": "HIGH",
            "initiating_events": [{"kind": "ASSET_FAILURE", "asset_code": "SUB-02"}],
        },
    )
    assert r.status_code == 201, r.text
    incident = r.json()
    assert incident["reference"].startswith("INC-")
    assert incident["analysis_available"] is True
    sim = await run(client, incident_id=incident["id"])
    assert sim["incident_id"] == incident["id"]
    listed = (await client.get("/simulations", params={"incident_id": incident["id"]})).json()
    assert [i["id"] for i in listed["items"]] == [sim["id"]]
    assert (await client.get(f"/incidents/{incident['id']}")).json()["reference"] == incident[
        "reference"
    ]


async def test_free_text_incident_is_stored_but_not_simulatable_yet(client: AsyncClient) -> None:
    r = await client.post(
        "/incidents",
        json={
            "source": "FREE_TEXT",
            "raw_report": "Explosion at the Riverside substation, lights out.",
        },
    )
    incident = r.json()
    assert r.status_code == 201
    assert incident["analysis_available"] is False
    assert "initiating_events" in incident["missing_information"]
    blocked = await client.post("/simulations", json={"incident_id": incident["id"]})
    assert blocked.status_code == 409


async def test_invalid_incidents_are_rejected(client: AsyncClient) -> None:
    for body in (
        {"source": "STRUCTURED", "title": "x" * 5, "incident_type": "POWER_FAILURE",
         "severity": "HIGH",
         "initiating_events": [{"kind": "ASSET_FAILURE", "asset_code": "NOPE-01"}]},
        {"source": "FREE_TEXT", "raw_report": "short"},
        {"source": "CARRIER_PIGEON", "raw_report": "a long enough report text"},
    ):  # fmt: skip
        assert (await client.post("/incidents", json=body)).status_code == 422


async def test_structural_criticality(client: AsyncClient) -> None:
    report = (await client.get("/infrastructure/criticality")).json()
    entries = {e["code"]: e for e in report["entries"]}
    assert len(entries) == 43
    assert entries["SUB-02"]["single_point_of_failure"] is True
    assert set(entries["SUB-02"]["critical_failed"]) == {"HOS-02", "WTP-01"}
    assert entries["SOL-01"]["single_point_of_failure"] is False  # off-grid island only
    assert entries["SUB-02"]["impact_score"] == 49.62  # equals the substation scenario


async def test_capabilities_report_simulation(client: AsyncClient) -> None:
    caps = (await client.get("/system/status")).json()["capabilities"]
    assert caps["phase"] >= 2
    assert caps["simulation"] is True
