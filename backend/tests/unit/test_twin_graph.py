from __future__ import annotations

import pytest

from app.graph.model import AssetCategory as C
from app.graph.model import DependencyMode, ServiceType, UnknownAssetError
from app.graph.twin_graph import Direction, TwinGraph
from tests.factories import asset, dep, snapshot


@pytest.fixture
def chain() -> TwinGraph:
    """GSP -> SUB -> PDN -> HOS, plus a SCADA cycle SUB <-(soft telecom)- HUB <- PDN,
    and a road giving access to HOS."""
    return TwinGraph(
        snapshot(
            [
                asset("GSP-01", C.GRID_SUPPLY),
                asset("SUB-01", C.SUBSTATION),
                asset("PDN-01", C.POWER_DISTRIBUTION),
                asset("HOS-01", C.HOSPITAL),
                asset("TEL-HUB", C.TELECOM_HUB),
                asset("RD-01", C.ROAD_SEGMENT),
            ],
            [
                dep("GSP-01", "SUB-01"),
                dep("SUB-01", "PDN-01"),
                dep("PDN-01", "HOS-01"),
                dep("PDN-01", "TEL-HUB"),
                dep("TEL-HUB", "SUB-01", ServiceType.TELECOM, DependencyMode.SOFT, "scada"),
                dep("RD-01", "HOS-01", ServiceType.ACCESS, DependencyMode.SOFT, "access"),
            ],
        )
    )


def test_downstream_with_depths_and_paths(chain: TwinGraph) -> None:
    hits = chain.downstream("GSP-01")
    assert [(h.code, h.depth) for h in hits] == [
        ("SUB-01", 1), ("PDN-01", 2), ("HOS-01", 3), ("TEL-HUB", 3),
    ]  # fmt: skip
    assert next(h for h in hits if h.code == "HOS-01").path == (
        "GSP-01",
        "SUB-01",
        "PDN-01",
        "HOS-01",
    )


def test_cycles_terminate_and_focus_is_excluded(chain: TwinGraph) -> None:
    codes = [h.code for h in chain.downstream("SUB-01")]
    assert "SUB-01" not in codes
    assert sorted(codes) == ["HOS-01", "PDN-01", "TEL-HUB"]


def test_upstream_includes_cycle_members(chain: TwinGraph) -> None:
    assert {h.code for h in chain.upstream("HOS-01")} == {"PDN-01", "SUB-01", "GSP-01", "TEL-HUB"}


def test_access_edges_excluded_by_default(chain: TwinGraph) -> None:
    assert chain.downstream("RD-01") == []
    assert "RD-01" not in {h.code for h in chain.upstream("HOS-01")}


def test_access_edges_only_followed_from_focus(chain: TwinGraph) -> None:
    assert [h.code for h in chain.downstream("RD-01", include_access=True)] == ["HOS-01"]
    # Access is not transitive: from GSP-01 the road never appears, even when included.
    assert "RD-01" not in {h.code for h in chain.upstream("HOS-01", include_access=False)}


def test_max_depth(chain: TwinGraph) -> None:
    assert [h.code for h in chain.downstream("GSP-01", max_depth=1)] == ["SUB-01"]


def test_service_type_filter(chain: TwinGraph) -> None:
    hits = chain.traverse("PDN-01", Direction.DOWNSTREAM, service_types=[ServiceType.TELECOM])
    assert hits == []


def test_unknown_asset_rejected(chain: TwinGraph) -> None:
    with pytest.raises(UnknownAssetError):
        chain.downstream("XX-99")
    with pytest.raises(UnknownAssetError):
        chain.providers_of("XX-99")


def test_duplicate_codes_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate asset codes"):
        snapshot([asset("SUB-01"), asset("SUB-01")], [])
