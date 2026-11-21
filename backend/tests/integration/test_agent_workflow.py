"""End-to-end agent workflow on PostgreSQL (docs/AGENT_DESIGN.md §5): deterministic mode,
clarification, fault injection and grounding enforcement."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.schemas import Briefing, IncidentExtraction, Narrative
from app.core.config import Settings
from app.llm.base import LLMTimeoutError, ProviderResponse, TokenUsage
from app.llm.chain import LLMClient
from app.main import create_app

STRUCTURED = {
    "source": "STRUCTURED",
    "title": "Transformer fire at Riverside",
    "incident_type": "POWER_FAILURE",
    "severity": "HIGH",
    "initiating_events": [{"kind": "ASSET_FAILURE", "asset_code": "SUB-02"}],
}


async def new_incident(client: AsyncClient, body: dict[str, Any]) -> str:
    r = await client.post("/incidents", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]  # type: ignore[no-any-return]


async def analyze(client: AsyncClient, incident_id: str) -> str:
    r = await client.post(f"/incidents/{incident_id}/analyze")
    assert r.status_code == 202, r.text
    return r.json()["workflow_run_id"]  # type: ignore[no-any-return]


async def wait(client: AsyncClient, run_id: str, limit_s: float = 60) -> dict[str, Any]:
    async with asyncio.timeout(limit_s):
        while True:
            body = (await client.get(f"/workflows/{run_id}")).json()
            if body["status"] in ("COMPLETED", "FAILED", "AWAITING_CLARIFICATION"):
                return body  # type: ignore[no-any-return]
            await asyncio.sleep(0.1)


def by_agent(run: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for e in run["executions"]:
        out.setdefault(e["agent"], []).append(e)
    return out


# ------------------------------------------------------------------ deterministic mode
async def test_structured_incident_full_workflow(client: AsyncClient) -> None:
    incident_id = await new_incident(client, STRUCTURED)
    run = await wait(client, await analyze(client, incident_id))
    assert run["status"] == "COMPLETED", run["error"]
    assert run["llm_mode"] == "DETERMINISTIC"
    agents = by_agent(run)
    assert list(agents) == ["SENTINEL", "CARTOGRAPHER", "ORACLE"]
    assert all(e["status"] == "SUCCEEDED" for e in run["executions"])

    sentinel = agents["SENTINEL"][0]["output"]
    assert sentinel["source"] == "STRUCTURED"
    assert sentinel["confidence"] == 1.0

    carto = agents["CARTOGRAPHER"][0]
    assert carto["output"]["single_points_of_failure"][0]["code"] == "SUB-02"
    assert carto["grounding"]["ok"] is True
    lost = {
        r["dependent"]
        for r in carto["output"]["redundancy_effects"]
        if r["effect"] == "REQUIREMENT_LOST"
    }
    assert {"PDN-03", "PDN-04"} <= lost
    support = {
        r["dependent"]
        for r in carto["output"]["redundancy_effects"]
        if r["effect"] == "SUPPORT_LOST"
    }
    assert "HOS-02" not in lost  # its power group lost, but only via PDN-03 (not SUB-02 directly)
    assert support.isdisjoint(lost)
    assert [t["name"] for t in carto["tool_calls"]] == [
        "structural_criticality",
        "dependency_analysis",
    ]

    oracle = agents["ORACLE"][0]["output"]
    assert oracle["affected_population"] == 176_000  # same as the golden scenario
    assert {d["asset"] for d in oracle["deadlines"] if d["exhausted_within_horizon"]} == {
        "HOS-02", "TEL-03", "TEL-04",
    }  # fmt: skip
    hos02 = next(c for c in oracle["key_chains"] if c["asset"] == "HOS-02")
    assert hos02["chain"] == ["HOS-02", "PDN-03", "SUB-02"]

    incident = (await client.get(f"/incidents/{incident_id}")).json()
    assert incident["status"] == "ANALYZED"
    picture = (await client.get("/operational-picture")).json()
    assert picture["simulation_id"] == oracle["simulation_id"]
    audit = (await client.get("/audit", params={"entity_id": run["id"]})).json()["items"]
    assert {a["action"] for a in audit} >= {"workflow.started", "workflow.completed"}


async def test_free_text_report_is_analysed_and_becomes_simulatable(client: AsyncClient) -> None:
    incident_id = await new_incident(client, {
        "source": "FREE_TEXT",
        "raw_report": "Explosion reported at the Riverside substation around 06:40. East bank "
        "lights out, Riverside Community Hospital running on generator.",
    })  # fmt: skip
    run = await wait(client, await analyze(client, incident_id))
    assert run["status"] == "COMPLETED"
    assessment = run["result"]["assessment"]
    assert [m["code"] for m in assessment["affected_assets"] if m["role"] == "damaged"] == [
        "SUB-02"
    ]
    assert [m["code"] for m in assessment["affected_assets"] if m["role"] == "affected"] == [
        "HOS-02"
    ]
    assert any(e["kind"] == "REPORT_SPAN" for e in assessment["evidence"])
    incident = (await client.get(f"/incidents/{incident_id}")).json()
    assert incident["analysis_available"] is True
    assert incident["incident_type"] == "POWER_FAILURE"


async def test_low_confidence_report_waits_for_operator_then_completes(client: AsyncClient) -> None:
    incident_id = await new_incident(client, {
        "source": "FREE_TEXT",
        "raw_report": "Something happened downtown, lots of sirens and people gathering.",
    })  # fmt: skip
    run_id = await analyze(client, incident_id)
    run = await wait(client, run_id)
    assert run["status"] == "AWAITING_CLARIFICATION"
    assert "affected_asset" in run["pending_question"]["missing_information"]
    assert (await client.get(f"/incidents/{incident_id}")).json()["status"] == "ANALYZING"

    bad = await client.post(f"/workflows/{run_id}/clarify", json={"asset_codes": ["NOPE-99"]})
    assert bad.status_code == 422
    ok = await client.post(
        f"/workflows/{run_id}/clarify",
        json={"asset_codes": ["SUB-01"], "incident_type": "POWER_FAILURE", "severity": "HIGH"},
    )
    assert ok.status_code == 202
    run = await wait(client, run_id)
    assert run["status"] == "COMPLETED", run["error"]
    sentinels = by_agent(run)["SENTINEL"]
    assert [e["attempt"] for e in sentinels] == [1, 2]
    assert sentinels[1]["output"]["affected_assets"][0]["method"] == "operator"
    again = await client.post(f"/workflows/{run_id}/clarify", json={"asset_codes": ["SUB-01"]})
    assert again.status_code == 409


async def test_only_one_active_analysis_per_incident(client: AsyncClient) -> None:
    incident_id = await new_incident(client, {
        "source": "FREE_TEXT", "raw_report": "Sirens everywhere near the river, unclear what.",
    })  # fmt: skip
    run_id = await analyze(client, incident_id)
    await wait(client, run_id)  # parks in AWAITING_CLARIFICATION (still active)
    second = await client.post(f"/incidents/{incident_id}/analyze")
    assert second.status_code == 409


async def test_sse_stream_sends_workflow_snapshots(client: AsyncClient) -> None:
    incident_id = await new_incident(client, STRUCTURED)
    run_id = await analyze(client, incident_id)
    snapshots = []
    async with client.stream("GET", f"/workflows/{run_id}/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        async for line in r.aiter_lines():
            if line.startswith("data: "):
                snapshots.append(json.loads(line[6:]))
    assert snapshots[-1]["status"] == "COMPLETED"
    assert snapshots[-1]["id"] == run_id


async def test_agent_registry_and_activity(client: AsyncClient) -> None:
    agents = (await client.get("/agents")).json()
    assert [a["name"] for a in agents] == [
        "SENTINEL",
        "CARTOGRAPHER",
        "ORACLE",
        "STRATEGIST",
        "GUARDIAN",
    ]
    assert [a["available"] for a in agents] == [True, True, True, False, False]
    page = (await client.get("/agents/activity", params={"agent": "ORACLE", "limit": 1})).json()
    assert page["items"][0]["agent"] == "ORACLE"
    detail = (await client.get(f"/agents/executions/{page['items'][0]['id']}")).json()
    assert detail["output"]["result_hash"]
    status = (await client.get("/system/status")).json()
    assert status["capabilities"]["agents"] is True
    assert status["llm"] == "deterministic"


# ------------------------------------------------------------------ fault injection
class AlwaysTimeout:
    name, model = "flaky", "flaky-1"

    async def generate(self, request, *, timeout_s, repair_hint=None):  # type: ignore[no-untyped-def]
        raise LLMTimeoutError("simulated provider timeout")


class Hallucinator:
    """Valid extraction, but prose that invents an asset and a figure."""

    name, model = "hallucinator", "liar-1"

    async def generate(self, request, *, timeout_s, repair_hint=None):  # type: ignore[no-untyped-def]
        if request.schema is IncidentExtraction:
            value: Any = IncidentExtraction(
                incident_type="POWER_FAILURE", severity="HIGH", asset_mentions=[]
            )
        elif request.schema is Briefing:
            value = Briefing(text="SUB-99 also failed, affecting 98,765 people.")
        else:
            value = Narrative(text="Impact 87.65 with XYZ-01 destroyed.")
        return ProviderResponse(value=value, model=self.model, usage=TokenUsage(100, 20))


@pytest.fixture
async def client_with_llm(
    migrated_db: str, seeded: None, request: pytest.FixtureRequest
) -> AsyncIterator[AsyncClient]:
    app = create_app(
        Settings(database_url=migrated_db, aftermath_env="test", log_level="ERROR"),
        llm=LLMClient(request.param(), timeout_s=1, max_attempts=2),
    )
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://test/api/v1") as c,
    ):
        yield c


@pytest.mark.parametrize("client_with_llm", [AlwaysTimeout], indirect=True)
async def test_provider_outage_falls_back_to_deterministic(client_with_llm: AsyncClient) -> None:
    incident_id = await new_incident(client_with_llm, {
        "source": "FREE_TEXT",
        "raw_report": "Transformer fire at Southfield Substation, feeders down.",
    })  # fmt: skip
    run = await wait(client_with_llm, await analyze(client_with_llm, incident_id))
    assert run["status"] == "COMPLETED"
    assert run["llm_mode"] == "LLM"
    for e in run["executions"]:
        assert e["status"] == "FELL_BACK", e["agent"]
        attempts = [a["outcome"] for call in e["llm_calls"] for a in call.get("attempts", [])]
        assert attempts.count("LLMTimeoutError") == 2
    damaged = [
        m["code"] for m in run["result"]["assessment"]["affected_assets"] if m["role"] == "damaged"
    ]
    assert damaged == ["SUB-03"]


@pytest.mark.parametrize("client_with_llm", [Hallucinator], indirect=True)
async def test_ungrounded_llm_prose_is_never_shown(client_with_llm: AsyncClient) -> None:
    incident_id = await new_incident(client_with_llm, STRUCTURED)
    run = await wait(client_with_llm, await analyze(client_with_llm, incident_id))
    assert run["status"] == "COMPLETED"
    agents = by_agent(run)
    for name, field, source in (
        ("CARTOGRAPHER", "briefing", "briefing_source"),
        ("ORACLE", "narrative", "narrative_source"),
    ):
        e = agents[name][0]
        assert e["status"] == "FELL_BACK"
        assert e["grounding"]["ok"] is False
        assert e["output"][source] == "deterministic (grounding fallback)"
        assert "SUB-99" not in e["output"][field]
        assert "XYZ-01" not in e["output"][field]
    assert agents["CARTOGRAPHER"][0]["grounding"]["unknown_asset_codes"] == ["SUB-99"]
