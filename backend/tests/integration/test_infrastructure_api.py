from __future__ import annotations

import uuid

from httpx import AsyncClient


async def test_liveness_and_readiness(client: AsyncClient) -> None:
    assert (await client.get("/health")).json() == {"status": "ok"}
    ready = await client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {"database": "ok", "migrations": "ok", "dataset": "ok"}


async def test_every_response_is_marked_simulation_and_has_request_id(client: AsyncClient) -> None:
    r = await client.get("/infrastructure/health")
    assert r.headers["x-aftermath-environment"] == "SIMULATION"
    uuid.UUID(r.headers["x-request-id"])


async def test_valid_incoming_request_id_is_propagated(client: AsyncClient) -> None:
    rid = str(uuid.uuid4())
    r = await client.get("/health", headers={"x-request-id": rid})
    assert r.headers["x-request-id"] == rid
    r = await client.get("/health", headers={"x-request-id": "<script>"})
    assert r.headers["x-request-id"] != "<script>"


async def test_system_status_reports_capabilities_honestly(client: AsyncClient) -> None:
    body = (await client.get("/system/status")).json()
    assert body["simulation_notice"].startswith("SIMULATION ENVIRONMENT")
    assert body["dataset"]["asset_count"] == 50
    assert body["capabilities"]["digital_twin"] is True
    assert body["capabilities"]["recovery"] is False  # Phase 4


async def test_list_assets_and_filters(client: AsyncClient) -> None:
    all_assets = (await client.get("/infrastructure/assets")).json()
    assert len(all_assets["items"]) == 50
    assert all_assets["next_cursor"] is None
    assert all(a["synthetic"] is True for a in all_assets["items"])

    hospitals = (await client.get("/infrastructure/assets", params={"category": "HOSPITAL"})).json()
    assert [a["code"] for a in hospitals["items"]] == ["HOS-01", "HOS-02", "HOS-03"]

    multi = await client.get(
        "/infrastructure/assets", params=[("category", "HOSPITAL"), ("category", "FIRE_STATION")]
    )
    assert len(multi.json()["items"]) == 5

    critical = (await client.get("/infrastructure/assets", params={"min_criticality": 90})).json()
    assert {a["code"] for a in critical["items"]} == {"HOS-01", "HOS-02", "WTP-01", "EOC-01"}

    search = (await client.get("/infrastructure/assets", params={"q": "riverside"})).json()
    assert {a["code"] for a in search["items"]} >= {"SUB-02", "HOS-02", "WTP-01"}


async def test_pagination_walks_all_assets_exactly_once(client: AsyncClient) -> None:
    seen: list[str] = []
    cursor = None
    while True:
        params = {"limit": 7} | ({"cursor": cursor} if cursor else {})
        page = (await client.get("/infrastructure/assets", params=params)).json()
        seen += [a["code"] for a in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 50
    assert seen == sorted(set(seen))


async def test_invalid_filters_are_rejected(client: AsyncClient) -> None:
    for params in (
        {"category": "CASTLE"},
        {"min_criticality": 101},
        {"bbox": "1,2,3"},
        {"limit": 0},
    ):
        r = await client.get("/infrastructure/assets", params=params)
        assert r.status_code == 422, params
        assert r.headers["content-type"].startswith("application/problem+json")


async def test_asset_detail_includes_redundancy(client: AsyncClient) -> None:
    body = (await client.get("/infrastructure/assets/HOS-01")).json()
    power = next(g for g in body["requirements"] if g["group"] == "power")
    assert {p["code"] for p in power["providers"]} == {"PDN-02", "PDN-07"}
    assert power["spare_providers"] == 1
    assert body["recovery_profile"]["trade"] == "MECHANICAL"
    assert body["component_size"] == 44


async def test_unknown_asset_is_404_problem(client: AsyncClient) -> None:
    r = await client.get("/infrastructure/assets/XYZ-99")
    assert r.status_code == 404
    assert r.json()["type"].endswith("/not-found")
    assert (await client.get("/infrastructure/assets/XYZ-99/dependencies")).status_code == 404


async def test_dependency_traversal(client: AsyncClient) -> None:
    down = (await client.get("/infrastructure/assets/SUB-02/dependencies")).json()
    assert len(down["items"]) == 19
    up = (
        await client.get(
            "/infrastructure/assets/HOS-02/dependencies",
            params={"direction": "upstream", "service_type": "POWER"},
        )
    ).json()
    assert [i["asset"]["code"] for i in up["items"]] == ["PDN-03", "SUB-02", "GSP-01"]
    access = (
        await client.get(
            "/infrastructure/assets/RD-03/dependencies", params={"include_access": "true"}
        )
    ).json()
    assert {i["asset"]["code"] for i in access["items"]} >= {"SUB-02", "WTP-01", "HOS-02"}


async def test_graph_and_assets_are_consistent(client: AsyncClient) -> None:
    graph = (await client.get("/infrastructure/graph")).json()
    assets = (await client.get("/infrastructure/assets")).json()["items"]
    assert {n["code"] for n in graph["nodes"]} == {a["code"] for a in assets}
    by_code = {a["code"]: a for a in assets}
    for node in graph["nodes"]:
        assert node["position"] == by_code[node["code"]]["position"]
    assert len(graph["edges"]) == 131
    assert {n["component"] for n in graph["nodes"]} == {0, 1}


async def test_health_and_basemap(client: AsyncClient) -> None:
    health = (await client.get("/infrastructure/health")).json()
    assert health["picture"] == "baseline"
    assert health["population_total"] == 180000
    assert health["by_condition"] == {"INTACT": 50}
    basemap = (await client.get("/infrastructure/basemap")).json()
    assert basemap["type"] == "FeatureCollection"
    assert {f["properties"]["layer"] for f in basemap["features"]} >= {"water", "floodplain"}


async def test_audit_records_seeding(client: AsyncClient) -> None:
    page = (await client.get("/audit", params={"action": "dataset.seeded"})).json()
    assert page["items"]
    assert page["items"][0]["entity_id"].startswith("meridian-valley@")
    record = (await client.get(f"/audit/{page['items'][0]['id']}")).json()
    assert len(record["hash"]) == 64
    assert (await client.get("/audit/999999")).status_code == 404


async def test_readiness_reports_503_when_database_is_down() -> None:
    from httpx import ASGITransport

    from app.core.config import Settings
    from app.main import create_app

    unreachable = "postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none"
    app = create_app(Settings(database_url=unreachable, aftermath_env="test", log_level="ERROR"))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test/api/v1") as c:
            ready = await c.get("/health/ready")
            assert ready.status_code == 503
            assert ready.json()["checks"]["database"].startswith("unavailable")
            assert (await c.get("/health")).status_code == 200  # liveness is independent
            twin = await c.get("/infrastructure/health")
            assert twin.status_code == 503
            assert twin.json()["type"].endswith("-unavailable")
            assert "Traceback" not in twin.text
