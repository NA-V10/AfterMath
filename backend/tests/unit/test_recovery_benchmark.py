"""Optimality gap of the heuristic vs exhaustive serial-SGS enumeration (ADR-0004)."""

from __future__ import annotations

import pytest

from app.graph.model import TwinSnapshot
from app.recovery.benchmark import brute_force
from app.recovery.model import Policy
from tests.unit.test_recovery import INVENTORY, events


@pytest.mark.parametrize(
    "scenario", ["substation-riverside", "power-telecom-combined", "river-flood"]
)
def test_heuristic_is_optimal_on_predefined_scenarios(
    district: TwinSnapshot, scenario: str
) -> None:
    for policy in Policy:
        row = brute_force(district, events(scenario), INVENTORY, policy)
        assert row.gap_percent == 0.0, row


def test_heuristic_gap_on_contended_storm_is_within_threshold(district: TwinSnapshot) -> None:
    """ADR-0004: revisit an exact solver if the gap exceeds 10% on realistic instances."""
    rows = [brute_force(district, events("severe-storm"), INVENTORY, p) for p in Policy]
    assert all(r.gap_percent <= 10.0 for r in rows), rows
    assert all(r.feasible_orderings > 0 for r in rows)
