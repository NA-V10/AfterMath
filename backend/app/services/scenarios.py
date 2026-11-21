"""Predefined scenarios: file sync (seeding) and lookups."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidInputError, NotFoundError
from app.database.models import SimulationScenario
from app.graph.model import TwinSnapshot, UnknownAssetError
from app.services.audit import append_audit
from app.simulation.engine import InvalidScenarioError, validate_events
from app.simulation.model import InitiatingEvent, Scenario, SimulationConfig

EVENTS_ADAPTER: TypeAdapter[list[InitiatingEvent]] = TypeAdapter(list[InitiatingEvent])


def scenario_hash(scenario: Scenario) -> str:
    canonical = json.dumps(scenario.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def load_scenario_files(directory: Path) -> list[Scenario]:
    return [
        Scenario.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(directory.glob("*.json"))
    ]


def check_events(snapshot: TwinSnapshot, events: Sequence[InitiatingEvent], horizon: int) -> None:
    """Deterministic validation of initiating events against the twin (422 on failure)."""
    try:
        validate_events(snapshot, events, SimulationConfig(horizon_minutes=horizon))
    except UnknownAssetError as exc:
        raise InvalidInputError(f"Unknown asset code '{exc.code}' in initiating events.") from None
    except InvalidScenarioError as exc:
        raise InvalidInputError(str(exc)) from None


@dataclass(frozen=True, slots=True)
class SyncResult:
    created: list[str]
    updated: list[str]
    unchanged: list[str]


async def sync_scenarios(
    session: AsyncSession, snapshot: TwinSnapshot, scenarios: list[Scenario], *, actor_id: str
) -> SyncResult:
    existing = {s.key: s for s in (await session.scalars(select(SimulationScenario))).all()}
    created, updated, unchanged = [], [], []
    for sc in scenarios:
        check_events(snapshot, sc.initiating_events, sc.horizon_minutes)
        digest = scenario_hash(sc)
        events = [e.model_dump(mode="json") for e in sc.initiating_events]
        row = existing.get(sc.key)
        if row is None:
            session.add(
                SimulationScenario(
                    key=sc.key, name=sc.name, description=sc.description,
                    initiating_events=events, horizon_minutes=sc.horizon_minutes,
                    content_hash=digest,
                )
            )  # fmt: skip
            created.append(sc.key)
        elif row.content_hash != digest:
            row.name, row.description = sc.name, sc.description
            row.initiating_events, row.horizon_minutes = events, sc.horizon_minutes
            row.content_hash, row.version = digest, row.version + 1
            updated.append(sc.key)
        else:
            unchanged.append(sc.key)
    if created or updated:
        await append_audit(
            session, actor_type="SYSTEM", actor_id=actor_id, action="scenarios.synced",
            entity_type="simulation_scenario", details={"created": created, "updated": updated},
        )  # fmt: skip
    await session.flush()
    return SyncResult(created, updated, unchanged)


async def list_scenarios(session: AsyncSession) -> list[SimulationScenario]:
    return list(
        (await session.scalars(select(SimulationScenario).order_by(SimulationScenario.key))).all()
    )


async def get_scenario(session: AsyncSession, key: str) -> SimulationScenario:
    row = await session.scalar(select(SimulationScenario).where(SimulationScenario.key == key))
    if row is None:
        raise NotFoundError(f"Scenario '{key}' does not exist.")
    return row
