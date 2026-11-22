"""Grounding number variants: a deterministic template must pass its own grounding check."""

from __future__ import annotations

from app.agents.grounding import check_grounding, number_variants


def test_whole_floats_match_their_one_decimal_form() -> None:
    # Found in Phase 7: a plan with risk 60.0 failed grounding because only "60" was allowed.
    assert {"60", "60.0", "60.00"} <= number_variants([60.0])
    assert "10,475.0" in number_variants([10475.0])
    assert "60.0" not in number_variants([60])  # a true integer is never written with a decimal


def test_template_sentence_with_whole_float_risk_is_grounded() -> None:
    text = "Repair order: RD-04. Total impact 10475.0 impact-hours; risk 60.0."
    result = check_grounding(text, allowed_codes={"RD-04"}, allowed_numbers=[10475.0, 60.0])
    assert result.ok, result
