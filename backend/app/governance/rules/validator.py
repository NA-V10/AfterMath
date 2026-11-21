"""Deterministic plan validation (GUARDIAN). docs/RECOVERY_OPTIMIZATION.md §5.

The validator does not trust the planner: it rebuilds the action catalogue from the twin and the
incident and checks the stored plan against it, so a tampered or buggy plan (understated duration,
missing crew, unknown asset, over-allocation) is rejected. V-010..V-012 concern execution time and
are enforced by the governance service in Phase 5.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from app.graph.model import AssetCategory, PhysicalCondition, ServiceType, TwinSnapshot
from app.recovery.catalogue import incident_damage, repair_actions, temporary_power_actions
from app.recovery.evaluate import run
from app.recovery.model import ActionSpec, ActionType, Inventory, ScheduledAction
from app.simulation.model import ENGINE_VERSION, InitiatingEvent

RULES: dict[str, str] = {
    "V-001": "Every referenced asset exists in the twin and is synthetic",
    "V-002": "Action type is allowed for the asset's category and condition",
    "V-003": "Repairs target damaged assets; temporary power targets intact ones",
    "V-004": "Road access is open (or cleared earlier in the plan) when each action starts",
    "V-005": "Renewable resources (crews, generators, trucks) are never over-allocated",
    "V-006": "Total consumption stays within the resource inventory",
    "V-007": "Schedule integrity: catalogue durations/resources, start, horizon, no duplicates",
    "V-008": "Expected outcomes equal a fresh re-simulation of the plan",
    "V-009": "Content hash matches the stored strategy",
}


class RuleResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    rule: str
    description: str
    passed: bool
    findings: list[str]


class ValidationReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    passed: bool
    rules: list[RuleResult]
    engine_version: str
    snapshot_hash: str
    inventory_version: int


def content_hash(
    *,
    policy: str,
    inventory: Inventory,
    incident_events: Sequence[InitiatingEvent],
    actions: Sequence[ScheduledAction],
    horizon: int,
    expected_result_hash: str,
) -> str:
    """Canonical hash of everything an approval would cover (Phase 5 binds approvals to it)."""
    body = {
        "policy": policy,
        "inventory": inventory.model_dump(mode="json"),
        "incident_events": [e.model_dump(mode="json") for e in incident_events],
        "actions": [a.model_dump(mode="json") for a in actions],
        "horizon": horizon,
        "expected_result_hash": expected_result_hash,
    }
    text = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def _catalogue(
    snapshot: TwinSnapshot, events: Sequence[InitiatingEvent], horizon: int
) -> dict[str, ActionSpec]:
    damage = incident_damage(snapshot, events)
    specs = {s.key: s for s in repair_actions(snapshot, damage)}
    no_action = run(snapshot, events, [], horizon)
    specs |= {s.key: s for s in temporary_power_actions(snapshot, damage, no_action)}
    return specs


def validate_plan(
    snapshot: TwinSnapshot,
    incident_events: Sequence[InitiatingEvent],
    inventory: Inventory,
    actions: Sequence[ScheduledAction],
    *,
    horizon: int,
    expected_result_hash: str,
    stored_content_hash: str,
    policy: str,
) -> ValidationReport:
    findings: dict[str, list[str]] = {r: [] for r in RULES}
    damage = incident_damage(snapshot, incident_events)
    catalogue = _catalogue(snapshot, incident_events, horizon)
    known = snapshot.assets_by_code

    # V-001 / V-002 / V-003 ---------------------------------------------------------------
    for a in actions:
        asset = known.get(a.asset_code)
        if asset is None:
            findings["V-001"].append(f"#{a.seq} {a.asset_code}: unknown asset")
            continue
        if asset.metadata.get("synthetic") is not True:
            findings["V-001"].append(f"#{a.seq} {a.asset_code}: not marked synthetic")
        cond = (
            damage[a.asset_code].condition if a.asset_code in damage else PhysicalCondition.INTACT
        )
        has_power = any(
            d.dependent == a.asset_code and d.service_type is ServiceType.POWER
            for d in snapshot.dependencies
        )
        allowed = {
            ActionType.REPAIR: cond in (PhysicalCondition.DAMAGED, PhysicalCondition.DEGRADED),
            ActionType.REPLACE: cond is PhysicalCondition.DESTROYED,
            ActionType.DEPLOY_MOBILE_GENERATOR: has_power
            and asset.category is not AssetCategory.DEMAND_ZONE,
            ActionType.REFUEL_BACKUP: bool(asset.backup_power_hours),
        }[a.type]
        if not allowed:
            findings["V-002"].append(
                f"#{a.seq} {a.type.value} not allowed for {a.asset_code} ({cond.value})"
            )
        is_repair = a.type in (ActionType.REPAIR, ActionType.REPLACE)
        if is_repair != (a.asset_code in damage):
            findings["V-003"].append(
                f"#{a.seq} {a.type.value} on {a.asset_code}, which the incident "
                + ("did not damage" if is_repair else "damaged")
            )

    # V-004 access precedence ---------------------------------------------------------------
    repaired_at = {
        a.asset_code: a.end_minutes
        for a in actions
        if a.type in (ActionType.REPAIR, ActionType.REPLACE)
    }
    for a in actions:
        spec = catalogue.get(a.key)
        for g in spec.access if spec else ():
            open_count = sum(
                1
                for p in g.providers
                if p not in damage or repaired_at.get(p, 10**9) <= a.start_minutes
            )
            if open_count < g.k:
                findings["V-004"].append(
                    f"#{a.seq} {a.asset_code} starts at {a.start_minutes} without access via "
                    + "/".join(g.providers)
                )

    # V-005 renewable capacity (sweep) -------------------------------------------------------
    usage: dict[str, list[tuple[int, int]]] = {}
    for a in actions:
        for r in a.resources:
            usage.setdefault(r.resource, [])
            usage[r.resource] += [
                (a.start_minutes, r.units),
                (a.start_minutes + r.minutes, -r.units),
            ]
    for res, deltas in sorted(usage.items()):
        level = 0
        cap = inventory.renewables.get(res, 0)
        for t, d in sorted(deltas, key=lambda x: (x[0], x[1])):  # releases before acquisitions
            level += d
            if level > cap:
                findings["V-005"].append(f"{res}: {level} in use at T+{t} min (capacity {cap})")
                break

    # V-006 consumables ---------------------------------------------------------------------
    used: dict[str, int] = {}
    for a in actions:
        for k, v in a.consumables.items():
            used[k] = used.get(k, 0) + v
    for k, v in sorted(used.items()):
        if v > inventory.consumables.get(k, 0):
            findings["V-006"].append(
                f"{k}: needs {v}, inventory has {inventory.consumables.get(k, 0)}"
            )

    # V-007 integrity vs catalogue ----------------------------------------------------------
    seen: set[str] = set()
    for i, a in enumerate(actions, start=1):
        if a.seq != i:
            findings["V-007"].append(f"sequence numbers are not 1..n (#{a.seq} at position {i})")
        if a.key in seen:
            findings["V-007"].append(f"duplicate action {a.key}")
        seen.add(a.key)
        spec = catalogue.get(a.key)
        if spec is None:
            findings["V-007"].append(f"#{a.seq} {a.key} is not in the action catalogue")
            continue
        if a.end_minutes - a.start_minutes != spec.duration_minutes:
            findings["V-007"].append(
                f"#{a.seq} duration {a.end_minutes - a.start_minutes} "
                f"≠ catalogue {spec.duration_minutes}"
            )
        if a.start_minutes < spec.earliest_minutes:
            findings["V-007"].append(
                f"#{a.seq} starts at {a.start_minutes} before earliest {spec.earliest_minutes}"
            )
        if a.end_minutes > horizon:
            findings["V-007"].append(f"#{a.seq} ends after the horizon")
        if tuple(a.resources) != tuple(spec.resources) or a.consumables != spec.consumables:
            findings["V-007"].append(f"#{a.seq} resources/consumables differ from the catalogue")
        if a.supplies_minutes != spec.supplies_minutes:
            findings["V-007"].append(f"#{a.seq} supplied minutes differ from the catalogue")

    # V-008 re-simulation (a malformed plan is reported, never allowed to crash the validator) --
    if findings["V-001"]:
        findings["V-008"].append("not re-simulated: the plan references unknown assets")
    else:
        try:
            resim = run(snapshot, incident_events, actions, horizon).result_hash
        except (ValueError, KeyError) as exc:
            findings["V-008"].append(f"re-simulation rejected the plan: {exc}")
        else:
            if resim != expected_result_hash:
                findings["V-008"].append(
                    f"re-simulation hash {resim[:12]} ≠ stored {expected_result_hash[:12]}"
                )

    # V-009 content hash ------------------------------------------------------------------
    recomputed = content_hash(
        policy=policy,
        inventory=inventory,
        incident_events=incident_events,
        actions=actions,
        horizon=horizon,
        expected_result_hash=expected_result_hash,
    )
    if recomputed != stored_content_hash:
        findings["V-009"].append("stored content hash does not match the strategy's content")

    results = [
        RuleResult(rule=r, description=d, passed=not findings[r], findings=findings[r][:10])
        for r, d in RULES.items()
    ]
    return ValidationReport(
        passed=all(r.passed for r in results),
        rules=results,
        engine_version=ENGINE_VERSION,
        snapshot_hash=snapshot.content_hash,
        inventory_version=inventory.version,
    )
