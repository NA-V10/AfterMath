"""Recovery planner and GUARDIAN validator (docs/TESTING_STRATEGY.md P9, P10)."""

from __future__ import annotations

import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.governance.rules.validator import content_hash, validate_plan
from app.graph.model import TwinSnapshot
from app.recovery.model import Inventory, Plan, Policy, ResourceUse, ScheduledAction
from app.recovery.scheduler import plan
from app.simulation.engine import simulate
from app.simulation.model import (
    AssetFailureEvent,
    BackupSuppliedEvent,
    EventKind,
    FunctionalStatus,
    Scenario,
    SimulationConfig,
)
from tests.conftest import DATASET_DIR, SCENARIOS_DIR

RAW = json.loads((DATASET_DIR / "inventory.json").read_text(encoding="utf-8"))
INVENTORY = Inventory(version=1, renewables=RAW["renewables"], consumables=RAW["consumables"])


def events(key: str):  # type: ignore[no-untyped-def]
    path = SCENARIOS_DIR / f"{key}.json"
    return list(Scenario.model_validate_json(path.read_text(encoding="utf-8")).initiating_events)


def validate(snap: TwinSnapshot, ev, inv: Inventory, p: Plan, actions=None, *, policy=None):  # type: ignore[no-untyped-def]
    actions = p.actions if actions is None else actions
    pol = (policy or p.policy).value
    stored = content_hash(
        policy=p.policy.value, inventory=inv, incident_events=ev, actions=p.actions,
        horizon=p.horizon_minutes, expected_result_hash=p.expected_result_hash,
    )  # fmt: skip
    return validate_plan(
        snap, ev, inv, actions, horizon=p.horizon_minutes,
        expected_result_hash=p.expected_result_hash, stored_content_hash=stored, policy=pol,
    )  # fmt: skip


def failed(report) -> set[str]:  # type: ignore[no-untyped-def]
    return {r.rule for r in report.rules if not r.passed}


@pytest.fixture(scope="module")
def storm_plans(district: TwinSnapshot) -> dict[Policy, Plan]:
    return {p: plan(district, events("severe-storm"), INVENTORY, p) for p in Policy}


# ----------------------------------------------------------------- engine extension
def test_backup_supplied_event_keeps_an_asset_running(district: TwinSnapshot) -> None:
    ev = [AssetFailureEvent(asset_code="PDN-03")]
    base = simulate(district, ev, SimulationConfig(horizon_minutes=600))
    assert {a.code: a.status for a in base.final_state}["HOS-02"] is FunctionalStatus.FAILED
    fed = simulate(
        district, [*ev, BackupSuppliedEvent(t_minutes=120, asset_code="HOS-02", minutes=600)],
        SimulationConfig(horizon_minutes=600),
    )  # fmt: skip
    assert {a.code: a.status for a in fed.final_state}["HOS-02"] is FunctionalStatus.ON_BACKUP
    assert not any(
        e.kind is EventKind.BACKUP_EXHAUSTED and e.asset_code == "HOS-02" for e in fed.events
    )


# ----------------------------------------------------------------- planner behaviour
def test_plans_are_deterministic(district: TwinSnapshot) -> None:
    a = plan(district, events("severe-storm"), INVENTORY, Policy.BALANCED)
    b = plan(district, events("severe-storm"), INVENTORY, Policy.BALANCED)
    assert a == b


def test_policies_produce_distinct_trade_offs_under_contention(
    storm_plans: dict[Policy, Plan],
) -> None:
    orders = {
        p: [
            a.asset_code
            for a in plan_.actions
            if a.trade == "ELECTRICAL" and a.type.value == "REPAIR"
        ]
        for p, plan_ in storm_plans.items()
    }
    assert len({tuple(o) for o in orders.values()}) == 3  # three different electrical repair orders
    assert orders[Policy.CRITICAL_FIRST][0] == "SUB-02"  # hospital + water works first
    assert orders[Policy.BALANCED][0] == "PDN-01"  # 42,000 residents in 3 hours
    impact = {p: x.metrics.impact_hours for p, x in storm_plans.items()}
    assert min(impact, key=impact.get) is Policy.MAX_RESTORATION  # type: ignore[arg-type]


def test_every_damaged_asset_is_restored_when_resources_allow(
    storm_plans: dict[Policy, Plan],
) -> None:
    for p in storm_plans.values():
        assert p.metrics.unrestored_assets == []
        assert p.metrics.assets_restored == 6
        assert all(u.reason == "NO_BENEFIT" for u in p.unschedulable)


def test_road_clearance_precedes_access_dependent_repairs(storm_plans: dict[Policy, Plan]) -> None:
    for p in storm_plans.values():
        road = next(a for a in p.actions if a.asset_code == "RD-04")
        for code in ("SUB-04", "TEL-05"):
            act = next(a for a in p.actions if a.asset_code == code)
            assert act.start_minutes >= road.end_minutes
            assert road.seq in act.prerequisites


def test_insufficient_parts_are_reported_not_hidden(district: TwinSnapshot) -> None:
    ev = [
        AssetFailureEvent(asset_code="SUB-02", condition="DESTROYED"),
        AssetFailureEvent(asset_code="SUB-03", condition="DESTROYED"),
    ]  # one spare power transformer: only one substation can be replaced
    p = plan(district, ev, INVENTORY, Policy.CRITICAL_FIRST)
    replaced = [a.asset_code for a in p.actions if a.type.value == "REPLACE"]
    assert len(replaced) == 1
    missing = [u for u in p.unschedulable if u.reason == "INSUFFICIENT_RESOURCES"]
    assert [u.asset_code for u in missing] == sorted({"SUB-02", "SUB-03"} - set(replaced))
    assert "power_transformer" in missing[0].detail
    assert validate(district, ev, INVENTORY, p).passed


def test_all_predefined_scenarios_produce_valid_plans(district: TwinSnapshot) -> None:
    for key in ("substation-riverside", "river-flood", "power-telecom-combined", "severe-storm"):
        ev = events(key)
        for pol in Policy:
            report = validate(district, ev, INVENTORY, plan(district, ev, INVENTORY, pol))
            assert report.passed, (key, pol, failed(report))


# ----------------------------------------------------------------- P9: feasibility
@settings(max_examples=25, deadline=None)
@given(
    crews=st.integers(min_value=0, max_value=2),
    generators=st.integers(min_value=0, max_value=2),
    budget=st.sampled_from([0, 100_000, 900_000]),
    switchgear=st.integers(min_value=0, max_value=4),
    scenario=st.sampled_from(["severe-storm", "river-flood"]),
    policy=st.sampled_from(list(Policy)),
)
def test_p9_plans_never_exceed_resources(
    district: TwinSnapshot, crews: int, generators: int, budget: int, switchgear: int,
    scenario: str, policy: Policy,
) -> None:  # fmt: skip
    inv = Inventory(
        version=1,
        renewables={
            **INVENTORY.renewables,
            **{k: crews for k in INVENTORY.renewables if k.startswith("crew:")},
            "mobile_generator": generators,
        },
        consumables={**INVENTORY.consumables, "budget": budget, "switchgear_kit": switchgear},
    )  # fmt: skip
    ev = events(scenario)
    p = plan(district, ev, inv, policy)
    report = validate(district, ev, inv, p)
    assert report.passed, failed(report)
    # budget is a consumable too: the cost column must stay within it
    assert sum(a.consumables.get("budget", 0) for a in p.actions) <= budget


# ----------------------------------------------------------------- P10: validator rejects tampering
def _tamper(p: Plan, seq: int, **changes):  # type: ignore[no-untyped-def]
    return [a.model_copy(update=changes) if a.seq == seq else a for a in p.actions]


def test_p10_validator_rejects_tampered_plans(
    district: TwinSnapshot, storm_plans: dict[Policy, Plan]
) -> None:
    ev = events("severe-storm")
    p = storm_plans[Policy.BALANCED]
    assert validate(district, ev, INVENTORY, p).passed
    sub04 = next(a for a in p.actions if a.asset_code == "SUB-04")
    first = p.actions[0]

    shortened = _tamper(p, sub04.seq, end_minutes=sub04.end_minutes - 60)
    assert {"V-007", "V-008", "V-009"} <= failed(validate(district, ev, INVENTORY, p, shortened))

    early = _tamper(
        p, sub04.seq, start_minutes=30, end_minutes=30 + sub04.end_minutes - sub04.start_minutes
    )
    assert "V-004" in failed(validate(district, ev, INVENTORY, p, early))  # road not yet cleared

    no_crew = _tamper(
        p, first.seq, resources=(ResourceUse(resource="crew:CIVIL", units=0 + 1, minutes=1),)
    )
    assert "V-007" in failed(validate(district, ev, INVENTORY, p, no_crew))

    ghost = [
        *p.actions,
        first.model_copy(
            update={"seq": len(p.actions) + 1, "key": "REPAIR:HOS-01", "asset_code": "HOS-01"}
        ),
    ]
    assert {"V-002", "V-003", "V-007"} <= failed(validate(district, ev, INVENTORY, p, ghost))

    unknown = _tamper(p, first.seq, asset_code="ZZ-99")
    assert "V-001" in failed(validate(district, ev, INVENTORY, p, unknown))

    # Two parallel repairs on the single electrical crew: capacity violation.
    elec = [a for a in p.actions if a.trade == "ELECTRICAL"]
    duration = elec[1].end_minutes - elec[1].start_minutes
    start = elec[0].start_minutes
    overlapped = _tamper(p, elec[1].seq, start_minutes=start, end_minutes=start + duration)
    assert "V-005" in failed(validate(district, ev, INVENTORY, p, overlapped))

    poorer = INVENTORY.model_copy(
        update={"consumables": {**INVENTORY.consumables, "switchgear_kit": 0}}
    )
    assert "V-006" in failed(validate(district, ev, poorer, p))

    assert "V-009" in failed(validate(district, ev, INVENTORY, p, policy=Policy.CRITICAL_FIRST))


def test_scheduled_action_types_are_recorded(storm_plans: dict[Policy, Plan]) -> None:
    for p in storm_plans.values():
        assert all(isinstance(a, ScheduledAction) for a in p.actions)
        assert [a.seq for a in p.actions] == list(range(1, len(p.actions) + 1))
