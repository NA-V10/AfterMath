"""Semantics of functional evaluation on small hand-made twins."""

from __future__ import annotations

import pytest

from app.graph.model import AssetCategory as C
from app.graph.model import DependencyMode as M
from app.graph.model import PhysicalCondition as P
from app.graph.model import ServiceType as S
from app.graph.model import UnknownAssetError
from app.simulation.engine import InvalidScenarioError, simulate
from app.simulation.evaluator import DependencyIndex, evaluate
from app.simulation.model import (
    AssetFailureEvent,
    AssetRestoredEvent,
    EventKind,
    FunctionalStatus,
    InitialAssetState,
    SimulationConfig,
)
from tests.factories import asset, dep, snapshot

F, D, B, OK = (
    FunctionalStatus.FAILED,
    FunctionalStatus.DEGRADED,
    FunctionalStatus.ON_BACKUP,
    FunctionalStatus.OPERATIONAL,
)


def status_after(snap, *events, horizon: int = 600):  # type: ignore[no-untyped-def]
    r = simulate(snap, list(events), SimulationConfig(horizon_minutes=horizon))
    return {a.code: a.status for a in r.final_state}, r


REDUNDANT = snapshot(
    [asset("GSP-01", C.GRID_SUPPLY), asset("SUB-01"), asset("SUB-02"), asset("HOS-01", C.HOSPITAL)],
    [
        dep("GSP-01", "SUB-01"),
        dep("GSP-01", "SUB-02"),
        dep("SUB-01", "HOS-01", k=1),
        dep("SUB-02", "HOS-01", k=1),
    ],
)


def test_k_of_n_redundancy_tolerates_n_minus_k_losses() -> None:
    s, _ = status_after(REDUNDANT, AssetFailureEvent(asset_code="SUB-01"))
    assert s["HOS-01"] is OK
    s, _ = status_after(
        REDUNDANT, AssetFailureEvent(asset_code="SUB-01"), AssetFailureEvent(asset_code="SUB-02")
    )
    assert s["HOS-01"] is F


def test_physical_degradation_propagates_as_reduced_supply() -> None:
    s, r = status_after(
        snapshot(
            [
                asset("GSP-01", C.GRID_SUPPLY),
                asset("SUB-01"),
                asset("PDN-01", C.POWER_DISTRIBUTION),
            ],
            [dep("GSP-01", "SUB-01"), dep("SUB-01", "PDN-01")],
        ),
        AssetFailureEvent(asset_code="SUB-01", condition=P.DEGRADED),
    )
    assert s["SUB-01"] is D
    assert s["PDN-01"] is D
    assert {a.code: a.supply for a in r.final_state}["PDN-01"] == 1


def test_soft_loss_degrades_status_but_does_not_propagate() -> None:
    snap = snapshot(
        [asset("GSP-01", C.GRID_SUPPLY), asset("TEL-HUB", C.TELECOM_HUB), asset("SUB-01"),
         asset("PDN-01", C.POWER_DISTRIBUTION)],
        [dep("GSP-01", "SUB-01"), dep("GSP-01", "TEL-HUB"),
         dep("TEL-HUB", "SUB-01", S.TELECOM, M.SOFT, "scada"), dep("SUB-01", "PDN-01")],
    )  # fmt: skip
    s, _ = status_after(snap, AssetFailureEvent(asset_code="TEL-HUB"))
    assert s["SUB-01"] is D
    assert s["PDN-01"] is OK


def test_running_cycle_survives_until_something_external_fails() -> None:
    """Mutually-supporting HARD cycle fed by a source: the greatest fixed point keeps it alive."""
    snap = snapshot(
        [asset("GSP-01", C.GRID_SUPPLY), asset("SUB-01"), asset("TEL-HUB", C.TELECOM_HUB)],
        [dep("GSP-01", "SUB-01"), dep("SUB-01", "TEL-HUB"),
         dep("TEL-HUB", "SUB-01", S.TELECOM, M.HARD, "control")],
    )  # fmt: skip
    s, _ = status_after(snap)
    assert s == {"GSP-01": OK, "SUB-01": OK, "TEL-HUB": OK}
    s, _ = status_after(snap, AssetFailureEvent(asset_code="GSP-01"))
    assert s == {"GSP-01": F, "SUB-01": F, "TEL-HUB": F}


def test_backup_power_delays_failure_exactly() -> None:
    snap = snapshot(
        [asset("GSP-01", C.GRID_SUPPLY), asset("HOS-01", C.HOSPITAL, backup_power_hours=2.5)],
        [dep("GSP-01", "HOS-01")],
    )
    s, r = status_after(snap, AssetFailureEvent(asset_code="GSP-01", t_minutes=10))
    changes = [
        (e.t_minutes, e.to_status)
        for e in r.events
        if e.asset_code == "HOS-01" and e.kind is EventKind.STATUS_CHANGED
    ]
    assert changes == [(10, B), (160, F)]
    assert s["HOS-01"] is F


def test_restoration_before_exhaustion_preserves_remaining_backup() -> None:
    snap = snapshot(
        [asset("GSP-01", C.GRID_SUPPLY), asset("HOS-01", C.HOSPITAL, backup_power_hours=2)],
        [dep("GSP-01", "HOS-01")],
    )
    s, r = status_after(
        snap,
        AssetFailureEvent(asset_code="GSP-01", t_minutes=0),
        AssetRestoredEvent(asset_code="GSP-01", t_minutes=45),
    )
    assert s["HOS-01"] is OK
    state = {a.code: a for a in r.final_state}["HOS-01"]
    assert state.backup_remaining_minutes == 75
    assert not any(e.kind is EventKind.BACKUP_EXHAUSTED for e in r.events)


def test_restoration_from_initial_picture_brings_dependents_back() -> None:
    snap = snapshot(
        [asset("GSP-01", C.GRID_SUPPLY), asset("SUB-01"), asset("PDN-01", C.POWER_DISTRIBUTION)],
        [dep("GSP-01", "SUB-01"), dep("SUB-01", "PDN-01")],
    )
    initial = {"SUB-01": InitialAssetState(condition=P.DAMAGED, backup_remaining_minutes=0)}
    r = simulate(snap, [AssetRestoredEvent(asset_code="SUB-01", t_minutes=30)],
                 SimulationConfig(horizon_minutes=60), initial=initial)  # fmt: skip
    ups = [(e.asset_code, e.wave) for e in r.events if e.kind is EventKind.STATUS_CHANGED]
    assert ups == [("SUB-01", 0), ("PDN-01", 1)]
    assert r.timeline[0].failed == 2
    assert r.timeline[-1].failed == 0


def test_invalid_inputs_are_rejected() -> None:
    with pytest.raises(UnknownAssetError):
        simulate(REDUNDANT, [AssetFailureEvent(asset_code="XX-99")])
    with pytest.raises(InvalidScenarioError):
        simulate(REDUNDANT, [AssetFailureEvent(asset_code="SUB-01", t_minutes=999)],
                 SimulationConfig(horizon_minutes=60))  # fmt: skip


def test_evaluate_directly_reports_causes() -> None:
    idx = DependencyIndex(REDUNDANT)
    cond = {c: P.INTACT for c in idx.codes} | {"SUB-01": P.DAMAGED, "SUB-02": P.DAMAGED}
    ev = evaluate(idx, cond, {})
    cause = ev.causes["HOS-01"][0]
    assert cause.providers == ("SUB-01", "SUB-02")
    assert ev.status["HOS-01"] is F
