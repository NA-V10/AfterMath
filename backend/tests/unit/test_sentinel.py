"""SENTINEL's deterministic half: rule-based extraction + resolution on the labelled corpus."""

from __future__ import annotations

import json

import pytest

from app.agents.assessment import CLARIFICATION_THRESHOLD, apply_clarification, assess_report
from app.agents.resolver import rule_based_extraction
from app.agents.schemas import AssetMention, IncidentExtraction
from app.graph.model import TwinSnapshot
from tests.conftest import DATASET_DIR

CORPUS = json.loads((DATASET_DIR / "reports" / "corpus.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("report", CORPUS["reports"], ids=lambda r: r["id"])
def test_rule_based_sentinel_on_labelled_corpus(report: dict, district: TwinSnapshot) -> None:  # type: ignore[type-arg]
    a = assess_report(
        report["text"], rule_based_extraction(report["text"], district), district, provider="rules"
    )
    expected = report["expected"]
    damaged = sorted(m.code for m in a.affected_assets if m.role == "damaged")
    affected = sorted(m.code for m in a.affected_assets if m.role == "affected")
    assert damaged == expected["damaged"]
    assert affected == expected["affected"]
    assert a.needs_clarification is expected["needs_clarification"]
    if expected["incident_type"]:
        assert a.incident_type == expected["incident_type"]
    for code, condition in expected.get("conditions", {}).items():
        assert next(m.condition for m in a.affected_assets if m.code == code) == condition
    # Only damaged assets become initiating events.
    assert sorted(e.asset_code for e in a.initiating_events) == (  # type: ignore[union-attr]
        [] if a.needs_clarification else expected["damaged"]
    )


def test_prompt_injection_text_has_no_effect_beyond_extraction(district: TwinSnapshot) -> None:
    text = next(r["text"] for r in CORPUS["reports"] if r["id"] == "R09")
    a = assess_report(text, rule_based_extraction(text, district), district, provider="rules")
    assert [e.asset_code for e in a.initiating_events] == ["SUB-03"]  # type: ignore[union-attr]
    # The schema has no field through which an instruction could act.
    assert set(a.model_dump()) >= {"initiating_events", "confidence"}
    assert "approve" not in json.dumps(a.model_dump(mode="json")["initiating_events"])


def test_quotes_must_come_from_the_report(district: TwinSnapshot) -> None:
    """An extractor (e.g. an LLM) inventing a facility that is not in the text gets no event."""
    extraction = IncidentExtraction(
        incident_type="POWER_FAILURE",
        severity="HIGH",
        asset_mentions=[
            AssetMention(quote="Northgate Substation", role="damaged", condition="DAMAGED")
        ],
    )
    a = assess_report("A transformer fire somewhere east.", extraction, district, provider="fake")
    assert a.initiating_events == []
    assert a.needs_clarification
    assert any("unverifiable" in m for m in a.missing_information)


def test_ambiguous_mentions_lower_confidence(district: TwinSnapshot) -> None:
    extraction = IncidentExtraction(
        incident_type="POWER_FAILURE", severity="HIGH",
        asset_mentions=[AssetMention(quote="Riverside", role="damaged", condition="DAMAGED")],
    )  # fmt: skip
    a = assess_report("Riverside is out.", extraction, district, provider="fake")
    assert a.confidence < CLARIFICATION_THRESHOLD
    assert a.needs_clarification


def test_operator_clarification_replaces_damaged_assets(district: TwinSnapshot) -> None:
    text = "Something happened downtown, lots of sirens."
    a = assess_report(text, rule_based_extraction(text, district), district, provider="rules")
    assert a.needs_clarification
    c = apply_clarification(
        a, district, asset_codes=["SUB-01"], condition="DAMAGED", incident_type="POWER_FAILURE",
        severity=None,
    )  # fmt: skip
    assert not c.needs_clarification
    assert c.confidence == 1.0
    assert [e.asset_code for e in c.initiating_events] == ["SUB-01"]  # type: ignore[union-attr]
    assert c.incident_type == "POWER_FAILURE"
