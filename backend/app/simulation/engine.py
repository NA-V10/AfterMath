"""Discrete-event cascading-failure simulation (pure, deterministic).

    simulate(snapshot, events, config) -> SimulationResult

Within one instant, propagation is the fixed-point evaluation in `evaluator`. Across time, a
priority queue ordered by (t_minutes, sequence) advances the clock: initiating events, repairs
and backup-power exhaustion. Identical inputs always produce byte-identical results
(`result_hash`). See docs/SIMULATION_ENGINE.md §3-§7.
"""

from __future__ import annotations

import hashlib
import heapq
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import shape

from app.graph.model import AssetCategory, PhysicalCondition, TwinSnapshot, UnknownAssetError
from app.simulation.evaluator import DependencyIndex, Evaluation, evaluate, isolated_assets
from app.simulation.impact import compute_metrics
from app.simulation.model import (
    ENGINE_VERSION,
    SCORING_VERSION,
    AreaFloodEvent,
    AssetFailureEvent,
    AssetRestoredEvent,
    AssetState,
    BackupSuppliedEvent,
    EventKind,
    FunctionalStatus,
    ImpactMetrics,
    InitialAssetState,
    InitiatingEvent,
    SimEvent,
    SimulationConfig,
    SimulationResult,
    TimelinePoint,
)


class InvalidScenarioError(ValueError):
    pass


def flooded_assets(snapshot: TwinSnapshot, event: AreaFloodEvent) -> list[str]:
    """Assets inundated by a flood: geometry intersects the polygon and elevation is below the
    water level. Demand zones are excluded (residential flooding is out of scope)."""
    area = shape(event.polygon.model_dump(mode="json"))
    hit = []
    for a in snapshot.assets:
        if a.category is AssetCategory.DEMAND_ZONE or a.elevation_m is None:
            continue
        if a.elevation_m < event.water_level_m and area.intersects(
            shape(a.geometry.model_dump(mode="json"))
        ):
            hit.append(a.code)
    return hit


def validate_events(
    snapshot: TwinSnapshot, events: Sequence[InitiatingEvent], config: SimulationConfig
) -> None:
    for e in events:
        if e.t_minutes > config.horizon_minutes:
            raise InvalidScenarioError(
                f"event at t={e.t_minutes} is beyond the horizon ({config.horizon_minutes})"
            )
        if isinstance(e, AssetFailureEvent | AssetRestoredEvent | BackupSuppliedEvent):
            snapshot.asset(e.asset_code)  # raises UnknownAssetError


@dataclass(order=True)
class _Queued:
    t: int
    seq: int
    payload: Any = field(compare=False)


@dataclass(frozen=True)
class _BackupExhaustion:
    code: str
    token: int


class _Run:
    def __init__(
        self,
        snapshot: TwinSnapshot,
        config: SimulationConfig,
        initial: Mapping[str, InitialAssetState] | None,
    ) -> None:
        self.snapshot = snapshot
        self.config = config
        self.index = DependencyIndex(snapshot)
        self.conditions: dict[str, PhysicalCondition] = {}
        self.backup_left: dict[str, int] = {}
        for a in snapshot.assets:
            init = initial.get(a.code) if initial else None
            self.conditions[a.code] = init.condition if init else a.physical_condition
            full = round((a.backup_power_hours or 0) * 60)
            self.backup_left[a.code] = init.backup_remaining_minutes if init else full
        self.backup_since: dict[str, int] = {}
        self.backup_token: dict[str, int] = {}
        self.queue: list[_Queued] = []
        self.counter = 0
        self.events: list[SimEvent] = []
        self.timeline: list[TimelinePoint] = []
        self.peak: ImpactMetrics | None = None

    # -------------------------------------------------------------- helpers
    def push(self, t: int, payload: Any) -> None:
        self.counter += 1
        heapq.heappush(self.queue, _Queued(t, self.counter, payload))

    def emit(self, t: int, wave: int, kind: EventKind, code: str | None = None, **kw: Any) -> None:
        self.events.append(
            SimEvent(
                seq=len(self.events) + 1, t_minutes=t, wave=wave, kind=kind, asset_code=code, **kw
            )
        )

    def pending(self) -> int:
        """Events still queued beyond the horizon (stale backup timers excluded)."""
        return sum(
            1
            for q in self.queue
            if not isinstance(q.payload, _BackupExhaustion)
            or self.backup_token.get(q.payload.code) == q.payload.token
        )

    def available(self) -> dict[str, bool]:
        return {c: left > 0 for c, left in self.backup_left.items()}

    def evaluate(self, previous: Mapping[str, int] | None) -> tuple[Evaluation, frozenset[str]]:
        ev = evaluate(self.index, self.conditions, self.available(), previous)
        return ev, isolated_assets(self.index, ev.supply)

    def record(self, t: int, ev: Evaluation, isolated: frozenset[str]) -> ImpactMetrics:
        m = compute_metrics(self.snapshot, self.index, ev, isolated, t, self.config.scoring)
        impaired = sum(1 for s in ev.status.values() if s is not FunctionalStatus.OPERATIONAL)
        self.timeline.append(
            TimelinePoint(
                t_minutes=t,
                impact_score=m.impact_score,
                failed=m.status_counts[FunctionalStatus.FAILED],
                impaired=impaired,
                affected_population=m.affected_population,
            )
        )
        if self.peak is None or m.impact_score > self.peak.impact_score:
            self.peak = m
        return m

    # -------------------------------------------------------------- instant processing
    def apply(self, t: int, payload: Any, changed_phys: set[str]) -> bool:
        """Apply one queued item; returns False when it had no effect (e.g. a stale timer)."""
        if isinstance(payload, _BackupExhaustion):
            if self.backup_token.get(payload.code) != payload.token:
                return False  # stale: the asset left backup before exhaustion
            self.backup_left[payload.code] = 0
            self.emit(t, 0, EventKind.BACKUP_EXHAUSTED, payload.code)
            return True
        if isinstance(payload, BackupSuppliedEvent):
            code = payload.asset_code
            self.backup_left[code] += payload.minutes
            if code in self.backup_since:  # already on backup: move its exhaustion later
                self.backup_token[code] = self.backup_token.get(code, 0) + 1
                self.push(
                    t + self.backup_left[code], _BackupExhaustion(code, self.backup_token[code])
                )
            self.emit(
                t, 0, EventKind.BACKUP_SUPPLIED, code,
                details={"minutes": payload.minutes, "remaining_minutes": self.backup_left[code]},
            )  # fmt: skip
            return True
        targets: list[tuple[str, PhysicalCondition, dict[str, Any]]] = []
        if isinstance(payload, AssetFailureEvent):
            targets.append(
                (payload.asset_code, PhysicalCondition(payload.condition), {"cause": "initiating"})
            )
        elif isinstance(payload, AssetRestoredEvent):
            targets.append(
                (payload.asset_code, PhysicalCondition.INTACT, {"cause": "repair_completed"})
            )
        elif isinstance(payload, AreaFloodEvent):
            for code in flooded_assets(self.snapshot, payload):
                elev = self.snapshot.asset(code).elevation_m
                details = {
                    "cause": "flood",
                    "water_level_m": payload.water_level_m,
                    "elevation_m": elev,
                }
                targets.append((code, PhysicalCondition.DAMAGED, details))
        effective = False
        for code, condition, details in targets:
            before = self.conditions[code]
            if before is condition:
                continue
            effective = True
            self.conditions[code] = condition
            changed_phys.add(code)
            self.emit(
                t, 0, EventKind.CONDITION_CHANGED, code,
                details={**details, "from": before.value, "to": condition.value},
            )  # fmt: skip
        return effective

    def drain_backups(self, t: int) -> None:
        for code, since in self.backup_since.items():
            self.backup_left[code] = max(0, self.backup_left[code] - (t - since))
            self.backup_since[code] = t

    def status_wave(self, code: str, ev: Evaluation, changed_phys: set[str]) -> int:
        if code in ev.wave:
            return ev.wave[code]
        if code in changed_phys:
            return 0
        # A status-only change (e.g. engaging backup, losing a SOFT supply) happens as soon as
        # its first cause appears: the earliest cause whose changed providers have settled.
        cause_waves = [
            1 + max(ev.wave[p] for p in cause.providers if p in ev.wave)
            for cause in ev.causes[code]
            if any(p in ev.wave for p in cause.providers)
        ]
        return min(cause_waves) if cause_waves else 0

    def transition(
        self, t: int, prev: Evaluation, prev_iso: frozenset[str], ev: Evaluation,
        iso: frozenset[str], changed_phys: set[str],
    ) -> None:  # fmt: skip
        changes = []
        for code in self.index.codes:
            if prev.status[code] is not ev.status[code]:
                changes.append((self.status_wave(code, ev, changed_phys), code))
        for wave, code in sorted(changes):
            self.emit(
                t, wave, EventKind.STATUS_CHANGED, code,
                from_status=prev.status[code], to_status=ev.status[code],
                details={"causes": [c.model_dump(mode="json") for c in ev.causes[code]]},
            )  # fmt: skip
        for code in self.index.codes:
            engaged, was = code in ev.on_backup, code in self.backup_since
            if engaged and not was:
                self.backup_since[code] = t
                self.backup_token[code] = self.backup_token.get(code, 0) + 1
                left = self.backup_left[code]
                self.push(t + left, _BackupExhaustion(code, self.backup_token[code]))
                self.emit(
                    t, self.status_wave(code, ev, changed_phys), EventKind.BACKUP_ENGAGED, code,
                    details={"remaining_minutes": left, "exhausts_at": t + left},
                )  # fmt: skip
            elif was and not engaged:
                del self.backup_since[code]
                self.backup_token[code] = self.backup_token.get(code, 0) + 1  # invalidate timer
                self.emit(
                    t, self.status_wave(code, ev, changed_phys), EventKind.BACKUP_DISENGAGED, code,
                    details={"remaining_minutes": self.backup_left[code]},
                )  # fmt: skip
        for code in sorted(iso - prev_iso):
            self.emit(
                t, self.status_wave(code, ev, changed_phys), EventKind.ISOLATION_DETECTED, code
            )
        for code in sorted(prev_iso - iso):
            self.emit(
                t, self.status_wave(code, ev, changed_phys), EventKind.ISOLATION_RESOLVED, code
            )

    # -------------------------------------------------------------- main loop
    def run(
        self, events: Sequence[InitiatingEvent]
    ) -> tuple[Evaluation, frozenset[str], ImpactMetrics]:
        for e in sorted(enumerate(events), key=lambda ie: (ie[1].t_minutes, ie[0])):
            self.push(e[1].t_minutes, e[1])
        ev, iso = self.evaluate(None)
        # An initial (non-baseline) picture may already have assets on backup: `transition`
        # engages them (and schedules exhaustion) without emitting status changes.
        self.transition(0, ev, iso, ev, iso, set())
        metrics = self.record(0, ev, iso)
        horizon = self.config.horizon_minutes
        while self.queue and self.queue[0].t <= horizon:
            t = self.queue[0].t
            self.drain_backups(t)
            changed_phys: set[str] = set()
            effective = False
            while self.queue and self.queue[0].t == t:
                effective |= self.apply(t, heapq.heappop(self.queue).payload, changed_phys)
            if not effective:
                continue
            new_ev, new_iso = self.evaluate(ev.supply)
            self.transition(t, ev, iso, new_ev, new_iso, changed_phys)
            ev, iso = new_ev, new_iso
            metrics = self.record(t, ev, iso)
        self.drain_backups(horizon)
        self.emit(horizon, 0, EventKind.HORIZON_REACHED, details={"pending_events": self.pending()})
        final_metrics = metrics.model_copy(update={"t_minutes": horizon})
        return ev, iso, final_metrics


def _canonical_hash(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def simulate(
    snapshot: TwinSnapshot,
    events: Sequence[InitiatingEvent],
    config: SimulationConfig | None = None,
    *,
    initial: Mapping[str, InitialAssetState] | None = None,
) -> SimulationResult:
    """Run a deterministic simulation. Raises UnknownAssetError / InvalidScenarioError."""
    config = config or SimulationConfig()
    validate_events(snapshot, events, config)
    if initial is not None:
        unknown = sorted(set(initial) - set(snapshot.assets_by_code))
        if unknown:
            raise UnknownAssetError(unknown[0])
    run = _Run(snapshot, config, initial)
    ev, iso, final_metrics = run.run(events)
    final_state = tuple(
        AssetState(
            code=c,
            condition=run.conditions[c],
            supply=ev.supply[c],
            status=ev.status[c],
            on_backup=c in ev.on_backup,
            backup_remaining_minutes=run.backup_left[c],
            isolated=c in iso,
            causes=ev.causes[c],
        )
        for c in run.index.codes
    )
    assert run.peak is not None
    body = {
        "engine_version": ENGINE_VERSION,
        "scoring_version": SCORING_VERSION,
        "snapshot_hash": snapshot.content_hash,
        "horizon_minutes": config.horizon_minutes,
        "events": [e.model_dump(mode="json") for e in run.events],
        "final_state": [s.model_dump(mode="json") for s in final_state],
        "final_metrics": final_metrics.model_dump(mode="json"),
        "peak_metrics": run.peak.model_dump(mode="json"),
        "timeline": [p.model_dump(mode="json") for p in run.timeline],
    }
    inputs = {
        "events": [e.model_dump(mode="json") for e in events],
        "config": config.model_dump(mode="json"),
        "initial": {k: v.model_dump(mode="json") for k, v in sorted((initial or {}).items())},
    }
    result_hash = _canonical_hash({"inputs": inputs, **body})
    return SimulationResult.model_validate({**body, "result_hash": result_hash})
