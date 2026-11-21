"""Per-snapshot cache for derived, deterministic analyses (baseline picture, N-1 criticality).

Keyed by the snapshot content hash, so a re-seeded twin can never be served stale results.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.graph.model import TwinSnapshot
from app.simulation.criticality import CriticalityEntry, structural_criticality
from app.simulation.engine import simulate
from app.simulation.model import SimulationConfig, SimulationResult

CRITICALITY_HORIZON_MINUTES = 72 * 60

_cache: dict[tuple[str, str], Any] = {}
_lock = asyncio.Lock()


async def _cached(snapshot: TwinSnapshot, name: str, compute: Any) -> Any:
    key = (snapshot.content_hash, name)
    if key in _cache:
        return _cache[key]
    async with _lock:
        if key not in _cache:
            for stale in [k for k in _cache if k[0] != snapshot.content_hash]:
                del _cache[stale]
            _cache[key] = await asyncio.to_thread(compute)
        return _cache[key]


async def baseline(snapshot: TwinSnapshot) -> SimulationResult:
    result: SimulationResult = await _cached(
        snapshot, "baseline", lambda: simulate(snapshot, [], SimulationConfig(horizon_minutes=1))
    )
    return result


async def criticality(snapshot: TwinSnapshot) -> list[CriticalityEntry]:
    entries: list[CriticalityEntry] = await _cached(
        snapshot,
        "criticality",
        lambda: structural_criticality(snapshot, CRITICALITY_HORIZON_MINUTES),
    )
    return entries
