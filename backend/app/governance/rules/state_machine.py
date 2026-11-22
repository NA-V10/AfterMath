"""Strategy and incident lifecycles (docs/DATA_MODEL.md §9). Pure: the single place that says
which status changes are legal. Services call `require_*` before every mutation."""

from __future__ import annotations

from enum import StrEnum


class StrategyStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    VERIFIED = "VERIFIED"


S = StrategyStatus

STRATEGY_TRANSITIONS: dict[StrategyStatus, frozenset[StrategyStatus]] = {
    S.DRAFT: frozenset({S.VALIDATED, S.VALIDATION_FAILED, S.SUPERSEDED}),
    S.VALIDATED: frozenset({S.APPROVED, S.REJECTED, S.SUPERSEDED}),
    S.APPROVED: frozenset({S.EXECUTING, S.VALIDATION_FAILED, S.SUPERSEDED}),
    S.EXECUTING: frozenset({S.EXECUTED, S.EXECUTION_FAILED}),
    S.EXECUTED: frozenset({S.VERIFIED}),
    S.VALIDATION_FAILED: frozenset(),
    S.REJECTED: frozenset(),
    S.SUPERSEDED: frozenset(),
    S.EXECUTION_FAILED: frozenset(),
    S.VERIFIED: frozenset(),
}

TERMINAL = frozenset(s for s, nxt in STRATEGY_TRANSITIONS.items() if not nxt)
#: Statuses a new planning round may supersede (an approval is void once the plan is replaced).
SUPERSEDABLE = frozenset({S.DRAFT, S.VALIDATED, S.APPROVED})


class IncidentStatus(StrEnum):
    REPORTED = "REPORTED"
    ANALYZING = "ANALYZING"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    ANALYZED = "ANALYZED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RECOVERING = "RECOVERING"
    RECOVERED = "RECOVERED"
    CLOSED = "CLOSED"


I = IncidentStatus  # noqa: E741

#: Incidents whose strategies may still be approved or executed.
RECOVERABLE = frozenset({I.ANALYZED, I.AWAITING_APPROVAL})
#: Incidents that may be closed (anything not already closed; recovery need not succeed).
CLOSABLE = frozenset(set(IncidentStatus) - {I.CLOSED, I.ANALYZING, I.RECOVERING})


class TransitionError(ValueError):
    """An illegal status change. Carries a user-facing explanation."""


def can_transition(current: str, target: str) -> bool:
    try:
        return StrategyStatus(target) in STRATEGY_TRANSITIONS[StrategyStatus(current)]
    except ValueError:
        return False


def require_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        if StrategyStatus(current) in TERMINAL:
            raise TransitionError(f"Strategy is {current}, which is final; it cannot change.")
        raise TransitionError(f"Strategy is {current}; it cannot become {target}.")
