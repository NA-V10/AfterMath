"""SENTINEL's deterministic half: from an extraction (LLM or rules) to a validated assessment.

Pure functions (no I/O) so they can be tested exhaustively and reused by the clarification path.
"""

from __future__ import annotations

from app.agents.resolver import candidates, resolve_quote
from app.agents.schemas import (
    AssetMatch,
    Evidence,
    IncidentAssessment,
    IncidentExtraction,
)
from app.graph.model import PhysicalCondition, TwinSnapshot
from app.simulation.model import AssetFailureEvent

CLARIFICATION_THRESHOLD = 0.6
AMBIGUITY_PENALTY = 0.5


def assess_report(
    report: str, extraction: IncidentExtraction, snapshot: TwinSnapshot, *, provider: str
) -> IncidentAssessment:
    cands = candidates(snapshot)
    matches: dict[str, AssetMatch] = {}
    evidence: list[Evidence] = []
    missing = list(extraction.missing_information)
    low = report.lower()

    for mention in extraction.asset_mentions:
        start = low.find(mention.quote.lower())
        if start < 0:
            # An extractor must quote the report; anything else is not evidence.
            missing.append(f"unverifiable mention '{mention.quote[:40]}'")
            continue
        evidence.append(
            Evidence(
                kind="REPORT_SPAN", text=mention.quote, start=start, end=start + len(mention.quote)
            )
        )
        resolutions = resolve_quote(mention.quote, cands)
        if not resolutions:
            missing.append(f"unrecognised facility '{mention.quote[:40]}'")
            continue
        ambiguous = len(resolutions) > 1
        if ambiguous:
            missing.append(
                f"ambiguous facility '{mention.quote[:40]}': "
                + ", ".join(r.code for r in resolutions)
            )
        for r in resolutions:
            score = round(r.score * (AMBIGUITY_PENALTY if ambiguous else 1.0), 2)
            match = AssetMatch(
                code=r.code, name=r.name, quote=mention.quote, method=r.method,
                score=score, role=mention.role, condition=mention.condition,
            )  # fmt: skip
            previous = matches.get(r.code)
            # A facility reported as damaged anywhere is damaged; keep the strongest match.
            if previous is None or (match.role, match.score) > (previous.role, previous.score):
                matches[r.code] = match
            evidence.append(
                Evidence(kind="ASSET_MATCH", text=mention.quote, asset_code=r.code, score=score)
            )

    damaged = sorted((m for m in matches.values() if m.role == "damaged"), key=lambda m: m.code)
    affected = sorted((m for m in matches.values() if m.role == "affected"), key=lambda m: m.code)
    events = [
        AssetFailureEvent(asset_code=m.code, condition=PhysicalCondition(m.condition))
        for m in damaged
        if m.score >= CLARIFICATION_THRESHOLD
    ]
    if not damaged and "affected_asset" not in missing:
        missing.append("affected_asset")
    confidence = 0.0 if not damaged else min(m.score for m in damaged)
    if "incident_type" in missing:
        confidence = min(confidence, 0.5)
    confidence = round(confidence, 2)
    return IncidentAssessment(
        source="REPORT",
        incident_type=extraction.incident_type,
        severity=extraction.severity,
        affected_assets=[*damaged, *affected],
        initiating_events=events,
        confidence=confidence,
        evidence=evidence,
        missing_information=sorted(set(missing)),
        reported_consequences=list(extraction.reported_consequences),
        needs_clarification=confidence < CLARIFICATION_THRESHOLD or not events,
        extraction_provider=provider,
    )


def apply_clarification(
    assessment: IncidentAssessment,
    snapshot: TwinSnapshot,
    *,
    asset_codes: list[str],
    condition: str,
    incident_type: str | None,
    severity: str | None,
) -> IncidentAssessment:
    """An operator confirms the damaged assets: they replace the extracted ones (score 1.0)."""
    matches = [
        AssetMatch(
            code=c, name=snapshot.asset(c).name, quote="(operator)", method="operator",
            score=1.0, role="damaged", condition=condition,
        )
        for c in sorted(set(asset_codes))
    ]  # fmt: skip
    affected = [m for m in assessment.affected_assets if m.role == "affected"]
    return assessment.model_copy(
        update={
            "incident_type": incident_type or assessment.incident_type,
            "severity": severity or assessment.severity,
            "affected_assets": [*matches, *affected],
            "initiating_events": [
                AssetFailureEvent(asset_code=m.code, condition=PhysicalCondition(condition))
                for m in matches
            ],
            "confidence": 1.0,
            "evidence": [
                *assessment.evidence,
                *(
                    Evidence(kind="OPERATOR_NOTE", text="confirmed by operator", asset_code=m.code)
                    for m in matches
                ),
            ],
            "missing_information": [],
            "needs_clarification": False,
        }
    )
