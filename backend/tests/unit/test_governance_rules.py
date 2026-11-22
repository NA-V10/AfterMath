"""Pure governance rules: lifecycle, authorisation policies, execution-time revalidation
(V-010…V-012) and verification."""

from __future__ import annotations

import json

import pytest

from app.governance.rules.policies import (
    Role,
    StrategyFacts,
    decide_approval,
    decide_execution,
    has_role,
    highest,
)
from app.governance.rules.state_machine import (
    STRATEGY_TRANSITIONS,
    TERMINAL,
    StrategyStatus,
    TransitionError,
    can_transition,
    require_transition,
)
from app.governance.rules.validator import validate_execution, validate_plan
from app.governance.rules.verification import verify
from app.graph.model import PhysicalCondition, TwinSnapshot
from app.recovery.catalogue import incident_damage, repair_actions
from app.recovery.evaluate import run
from app.recovery.model import Inventory, Policy, ScheduledAction
from app.recovery.scheduler import plan
from app.simulation.model import AssetFailureEvent, FunctionalStatus, InitiatingEvent, Scenario
from tests.conftest import DATASET_DIR, SCENARIOS_DIR

RAW = json.loads((DATASET_DIR / "inventory.json").read_text(encoding="utf-8"))
INVENTORY = Inventory(version=1, renewables=RAW["renewables"], consumables=RAW["consumables"])
S = StrategyStatus
H = "a" * 64


def storm() -> list[InitiatingEvent]:
    path = SCENARIOS_DIR / "severe-storm.json"
    return list(Scenario.model_validate_json(path.read_text(encoding="utf-8")).initiating_events)


# ------------------------------------------------------------------ state machine
def test_terminal_states_have_no_exit_and_everything_else_does() -> None:
    assert {
        S.VALIDATION_FAILED,
        S.REJECTED,
        S.SUPERSEDED,
        S.EXECUTION_FAILED,
        S.VERIFIED,
    } == TERMINAL
    for s in TERMINAL:
        for t in StrategyStatus:
            assert not can_transition(s, t)
            with pytest.raises(TransitionError, match="final"):
                require_transition(s, t)


def test_execution_is_only_reachable_through_approval() -> None:
    sources = {s for s, nxt in STRATEGY_TRANSITIONS.items() if S.EXECUTING in nxt}
    assert sources == {S.APPROVED}
    approved_from = {s for s, nxt in STRATEGY_TRANSITIONS.items() if S.APPROVED in nxt}
    assert approved_from == {S.VALIDATED}
    assert not can_transition("DRAFT", "EXECUTING")
    assert not can_transition("NONSENSE", "APPROVED")


# ------------------------------------------------------------------ roles & policies
def test_roles_are_cumulative() -> None:
    assert highest(["viewer", "approver"]) is Role.APPROVER
    assert highest(["unknown"]) is Role.VIEWER
    assert has_role(["admin"], Role.APPROVER)
    assert has_role(["approver"], Role.OPERATOR)
    assert not has_role(["operator"], Role.APPROVER)
    assert not has_role([], Role.OPERATOR)


def facts(**kw: object) -> StrategyFacts:
    base: dict[str, object] = {
        "status": "VALIDATED", "content_hash": H, "incident_status": "AWAITING_APPROVAL",
        "planned_by": "olive", "sibling_statuses": ("VALIDATED", "VALIDATED"),
    }  # fmt: skip
    return StrategyFacts(**(base | kw))  # type: ignore[arg-type]


def approve(**kw: object):  # type: ignore[no-untyped-def]
    args: dict[str, object] = {
        "actor": "alice", "roles": ["approver"], "facts": facts(), "submitted_hash": H,
        "decision": "APPROVE", "comment": None, "separation_of_duties": True,
    }  # fmt: skip
    return decide_approval(**(args | kw))  # type: ignore[arg-type]


def test_approval_happy_path() -> None:
    assert approve().allowed


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"roles": ["operator"]}, "forbidden"),
        ({"actor": "olive"}, "forbidden"),  # separation of duties
        ({"facts": facts(status="DRAFT")}, "invalid-state-transition"),
        ({"facts": facts(status="REJECTED")}, "invalid-state-transition"),
        ({"facts": facts(incident_status="RECOVERED")}, "invalid-state-transition"),
        ({"submitted_hash": "b" * 64}, "content-hash-mismatch"),
        ({"decision": "REJECT", "comment": "  "}, "conflict"),
        ({"facts": facts(sibling_statuses=("APPROVED",))}, "conflict"),
        ({"facts": facts(sibling_statuses=("EXECUTED",))}, "conflict"),
    ],
)
def test_approval_denials(override: dict[str, object], code: str) -> None:
    d = approve(**override)
    assert not d.allowed
    assert d.code == code
    assert d.reason


def test_separation_of_duties_can_be_switched_off_and_reject_ignores_busy_siblings() -> None:
    assert approve(actor="olive", separation_of_duties=False).allowed
    assert approve(
        decision="REJECT", comment="too risky", facts=facts(sibling_statuses=("APPROVED",))
    ).allowed


def test_execution_policy() -> None:
    assert decide_execution(roles=["operator"], facts=facts(status="APPROVED")).allowed
    assert decide_execution(roles=["viewer"], facts=facts(status="APPROVED")).code == "forbidden"
    for status in ("VALIDATED", "REJECTED", "SUPERSEDED", "VALIDATION_FAILED", "DRAFT"):
        d = decide_execution(roles=["admin"], facts=facts(status=status))
        assert (d.allowed, d.code) == (False, "invalid-state-transition")


# ------------------------------------------------------------------ V-010 … V-012
@pytest.fixture(scope="module")
def storm_plan(district: TwinSnapshot):  # type: ignore[no-untyped-def]
    p = plan(district, storm(), INVENTORY, Policy.CRITICAL_FIRST)
    from app.governance.rules.validator import content_hash

    stored = content_hash(
        policy=p.policy.value, inventory=INVENTORY, incident_events=storm(), actions=p.actions,
        horizon=p.horizon_minutes, expected_result_hash=p.expected_result_hash,
    )  # fmt: skip
    report = validate_plan(
        district, storm(), INVENTORY, p.actions, horizon=p.horizon_minutes,
        expected_result_hash=p.expected_result_hash, stored_content_hash=stored,
        policy=p.policy.value,
    )  # fmt: skip
    assert report.passed
    return p, report


def revalidate(district: TwinSnapshot, storm_plan, **kw: object):  # type: ignore[no-untyped-def]
    p, report = storm_plan
    args: dict[str, object] = {
        "current_snapshot_hash": district.content_hash,
        "planned_snapshot_hash": district.content_hash,
        "planned_inventory_version": 1,
        "current_inventory": INVENTORY,
        "incident_matches": True,
        "incident_status": "AWAITING_APPROVAL",
        "sibling_statuses": ["VALIDATED", "SUPERSEDED"],
    }
    return validate_execution(report, p.actions, **(args | kw))  # type: ignore[arg-type]


def failed(report) -> set[str]:  # type: ignore[no-untyped-def]
    return {r.rule for r in report.rules if not r.passed}


def test_execution_revalidation_passes_when_nothing_changed(district, storm_plan) -> None:  # type: ignore[no-untyped-def]
    report = revalidate(district, storm_plan)
    assert report.passed
    assert [r.rule for r in report.rules][-3:] == ["V-010", "V-011", "V-012"]
    assert len(report.rules) == 12


def test_v010_new_inventory_that_still_fits_passes_but_shortage_fails(  # type: ignore[no-untyped-def]
    district, storm_plan
) -> None:
    richer = INVENTORY.model_copy(update={"version": 2})
    assert revalidate(district, storm_plan, current_inventory=richer).passed
    empty = Inventory(
        version=3, renewables=INVENTORY.renewables,
        consumables=dict.fromkeys(INVENTORY.consumables, 0),
    )  # fmt: skip
    report = revalidate(district, storm_plan, current_inventory=empty)
    assert failed(report) == {"V-010"}
    assert "no longer fits" in report.rules[9].findings[0]
    assert failed(revalidate(district, storm_plan, current_snapshot_hash="c" * 64)) == {"V-010"}


def test_v011_and_v012(district, storm_plan) -> None:  # type: ignore[no-untyped-def]
    assert failed(revalidate(district, storm_plan, incident_matches=False)) == {"V-011"}
    assert failed(revalidate(district, storm_plan, incident_status="CLOSED")) == {"V-011"}
    assert failed(revalidate(district, storm_plan, sibling_statuses=["EXECUTED"])) == {"V-012"}
    # An approved or rejected sibling does not block execution; an executing one does.
    assert revalidate(district, storm_plan, sibling_statuses=["APPROVED", "REJECTED"]).passed
    assert failed(revalidate(district, storm_plan, sibling_statuses=["EXECUTING"])) == {"V-012"}


# ------------------------------------------------------------------ verification
def test_verification_of_a_full_plan_matches_its_expectation(district, storm_plan) -> None:  # type: ignore[no-untyped-def]
    p, _ = storm_plan
    executed = run(district, storm(), p.actions, p.horizon_minutes)
    without = run(district, storm(), [], p.horizon_minutes)
    v = verify(district, p.actions, without_recovery=without, executed=executed,
               expected_result_hash=p.expected_result_hash)  # fmt: skip
    assert v.matches_expectation
    assert set(v.repaired_assets) == {e.asset_code for e in storm() if hasattr(e, "asset_code")}
    assert v.after.by_count > v.before.by_count
    assert v.after.by_population >= v.before.by_population
    assert v.impact_score_after < v.impact_score_before
    # A tampered expectation is detected, not trusted.
    wrong = verify(district, p.actions, without_recovery=without, executed=executed,
                   expected_result_hash="0" * 64)  # fmt: skip
    assert not wrong.matches_expectation


def test_repaired_but_not_functional_names_the_missing_supply(district: TwinSnapshot) -> None:
    events = [AssetFailureEvent(asset_code="SUB-02"), AssetFailureEvent(asset_code="PDN-03")]
    damage = incident_damage(district, events)
    spec = next(s for s in repair_actions(district, damage) if s.asset_code == "PDN-03")
    start = spec.earliest_minutes
    only_feeder = ScheduledAction(
        seq=1, key=spec.key, type=spec.type, asset_code="PDN-03",
        start_minutes=start, end_minutes=start + spec.duration_minutes,
        resources=spec.resources, consumables=spec.consumables, cost=spec.cost,
        trade=spec.trade, crew_size=1, rationale="test",
    )  # fmt: skip
    horizon = 2880
    executed = run(district, events, [only_feeder], horizon)
    without = run(district, events, [], horizon)
    v = verify(district, [only_feeder], without_recovery=without, executed=executed,
               expected_result_hash=executed.result_hash)  # fmt: skip
    assert v.repaired_assets == ["PDN-03"]
    [rnf] = v.repaired_not_functional
    assert rnf.code == "PDN-03"
    assert rnf.status is FunctionalStatus.FAILED
    assert "power unavailable" in rnf.reason
    assert "SUB-02" in rnf.reason
    sub = next(u for u in v.unresolved if u.code == "SUB-02")
    assert sub.reason == f"physically {PhysicalCondition.DAMAGED.value.lower()}"
    assert v.outcome == "PARTIALLY_RESTORED"
