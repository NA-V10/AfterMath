"""Golden tests: the three predefined scenarios against hand-derived expectations
(docs/TESTING_STRATEGY.md §3). Expectations were written from the dataset's dependency table
before the engine ran; they are not snapshots of engine output."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from app.graph.model import TwinSnapshot
from app.simulation.engine import simulate
from app.simulation.model import (
    EventKind,
    FunctionalStatus,
    Scenario,
    SimulationConfig,
    SimulationResult,
)
from tests.conftest import SCENARIOS_DIR

F, D, B, OK = (
    FunctionalStatus.FAILED,
    FunctionalStatus.DEGRADED,
    FunctionalStatus.ON_BACKUP,
    FunctionalStatus.OPERATIONAL,
)


def load(key: str) -> Scenario:
    return Scenario.model_validate_json((SCENARIOS_DIR / f"{key}.json").read_text(encoding="utf-8"))


def run(snapshot: TwinSnapshot, key: str) -> SimulationResult:
    sc = load(key)
    return simulate(
        snapshot, sc.initiating_events, SimulationConfig(horizon_minutes=sc.horizon_minutes)
    )


def statuses_at(
    result: SimulationResult, t: int, baseline: TwinSnapshot
) -> dict[str, FunctionalStatus]:
    """Replay STATUS_CHANGED events up to and including time t."""
    state = {a.code: OK for a in baseline.assets}
    for e in result.events:
        if e.t_minutes > t:
            break
        if e.kind is EventKind.STATUS_CHANGED and e.asset_code and e.to_status:
            state[e.asset_code] = e.to_status
    return state


def by_status(state: dict[str, FunctionalStatus], status: FunctionalStatus) -> set[str]:
    return {c for c, s in state.items() if s is status}


# ----------------------------------------------------------------- scenario 1
RIVERSIDE_FAILED_T0 = {
    "SUB-02",
    "PDN-03",
    "PDN-04",
    "WIN-01",
    "WTP-01",
    "WPS-02",
    "WPS-03",
    "ZN-04",
    "ZN-05",
}
RIVERSIDE_BACKUP_T0 = {"HOS-02", "TEL-03", "TEL-04"}
RIVERSIDE_DEGRADED = {"FUL-02", "HOS-01", "HOS-03", "ZN-01", "ZN-02", "ZN-03", "ZN-07"}


def test_riverside_substation_at_t0(district: TwinSnapshot) -> None:
    s = statuses_at(run(district, "substation-riverside"), 0, district)
    assert by_status(s, F) == RIVERSIDE_FAILED_T0
    assert by_status(s, B) == RIVERSIDE_BACKUP_T0
    assert by_status(s, D) == RIVERSIDE_DEGRADED


def test_riverside_backups_exhaust_on_schedule(district: TwinSnapshot) -> None:
    r = run(district, "substation-riverside")
    exhausted = {
        (e.asset_code, e.t_minutes) for e in r.events if e.kind is EventKind.BACKUP_EXHAUSTED
    }
    assert exhausted == {("TEL-03", 120), ("TEL-04", 120), ("HOS-02", 240)}
    final = {a.code: a.status for a in r.final_state}
    assert by_status(final, F) == RIVERSIDE_FAILED_T0 | RIVERSIDE_BACKUP_T0
    assert r.final_metrics.affected_population == 176_000
    assert r.final_metrics.population_by_service["POWER"] == 45_000  # ZN-04 + ZN-05


def test_riverside_cascade_waves(district: TwinSnapshot) -> None:
    r = run(district, "substation-riverside")
    wave = {
        e.asset_code: e.wave
        for e in r.events
        if e.kind is EventKind.STATUS_CHANGED and e.t_minutes == 0
    }
    assert wave["SUB-02"] == 0
    assert wave["PDN-03"] == wave["PDN-04"] == 1
    assert wave["WTP-01"] == wave["HOS-02"] == wave["TEL-03"] == 2
    assert wave["WPS-02"] == 3
    assert wave["HOS-01"] == 4


def test_riverside_leaves_unrelated_assets_untouched(district: TwinSnapshot) -> None:
    final = {a.code: a.status for a in run(district, "substation-riverside").final_state}
    untouched = {
        "GSP-01", "GSP-02", "SUB-01", "SUB-03", "SUB-04", "PDN-01", "PDN-02", "PDN-05", "PDN-06",
        "PDN-07", "TEL-HUB", "TEL-01", "TEL-02", "TEL-05", "DC-01", "EOC-01", "FIR-01", "FIR-02",
        "FUL-01", "SOL-01", "WIN-02", "WTP-02", "WPS-01", "ZN-06",
    }  # fmt: skip
    assert {c for c in untouched if final[c] is not OK} == set()


def test_hospital_on_generator_is_detected_as_isolated(district: TwinSnapshot) -> None:
    r = run(district, "substation-riverside")
    isolated = {e.asset_code for e in r.events if e.kind is EventKind.ISOLATION_DETECTED}
    assert isolated == {"HOS-02"}


# ----------------------------------------------------------------- scenario 2
def test_flood_inundates_low_lying_assets_only(district: TwinSnapshot) -> None:
    r = run(district, "river-flood")
    flooded = {
        e.asset_code
        for e in r.events
        if e.kind is EventKind.CONDITION_CHANGED and e.details.get("cause") == "flood"
    }
    assert flooded == {"SUB-02", "WIN-01", "WTP-01", "FUL-02", "BR-01", "RD-03"}
    final = {a.code: a.status for a in r.final_state}
    assert final["FUL-02"] is F  # inundated, not merely without pumps
    assert final["WPS-03"] is F  # above the water, but loses power and treated water
    assert final["FIR-02"] is OK  # fuel still available from FUL-01 (1-of-2)


# ----------------------------------------------------------------- scenario 3
def test_combined_power_and_telecom(district: TwinSnapshot) -> None:
    r = run(district, "power-telecom-combined")
    s0 = statuses_at(r, 0, district)
    assert s0["HOS-01"] is D  # loses water, but keeps power via PDN-07 (N-1 redundancy)
    assert by_status(s0, B) == {"TEL-HUB", "TEL-01", "TEL-02", "DC-01", "EOC-01"}
    assert s0["EOC-01"] is B

    s30 = statuses_at(r, 30, district)
    assert by_status(s30, F) >= {
        "TEL-HUB",
        "TEL-01",
        "TEL-02",
        "TEL-03",
        "TEL-04",
        "TEL-05",
        "DC-01",
        "EOC-01",
    }
    assert {s30[c] for c in ("SUB-02", "SUB-03", "SUB-04")} == {D}  # SCADA loss is SOFT
    # SCADA loss must not brown out the grid: their feeders stay fully operational.
    assert {s30[c] for c in ("PDN-03", "PDN-04", "PDN-05", "PDN-06", "PDN-07")} == {OK}


def test_damaged_asset_does_not_run_on_backup(district: TwinSnapshot) -> None:
    r = run(district, "power-telecom-combined")
    hub = [e for e in r.events if e.asset_code == "TEL-HUB" and e.kind.name.startswith("BACKUP")]
    assert [(e.kind, e.t_minutes) for e in hub] == [
        (EventKind.BACKUP_ENGAGED, 0),
        (EventKind.BACKUP_DISENGAGED, 30),
    ]


# ----------------------------------------------------------------- determinism (P1)
@pytest.mark.parametrize("key", ["substation-riverside", "river-flood", "power-telecom-combined"])
def test_identical_inputs_produce_identical_results(district: TwinSnapshot, key: str) -> None:
    a, b = run(district, key), run(district, key)
    assert a.result_hash == b.result_hash
    assert a.model_dump() == b.model_dump()


def test_result_hash_is_stable_across_processes_and_hash_seeds(district: TwinSnapshot) -> None:
    here = run(district, "substation-riverside").result_hash
    code = (
        "from tests.unit.test_simulation_golden import run; from tests.conftest import DATASET_DIR;"
        "from app.graph.dataset import load_dataset_dir, to_snapshot;"
        "snap = to_snapshot(load_dataset_dir(DATASET_DIR)[0]);"
        "print(run(snap, 'substation-riverside').result_hash)"
    )
    for seed in ("1", "987654"):
        out = subprocess.run(  # noqa: S603
            [sys.executable, "-c", code],
            capture_output=True, text=True, check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )  # fmt: skip
        assert out.stdout.strip() == here


def test_scenario_files_parse(district: TwinSnapshot) -> None:
    for path in sorted(SCENARIOS_DIR.glob("*.json")):
        Scenario.model_validate(json.loads(path.read_text(encoding="utf-8")))
