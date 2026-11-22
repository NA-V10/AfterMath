"""Authorisation policies (docs/SECURITY.md §3). Pure and unit-tested: given who is acting and
the facts about a strategy, decide whether an approval, rejection or execution is allowed.

Roles are cumulative: viewer < operator < approver < admin.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from app.governance.rules.state_machine import RECOVERABLE, StrategyStatus


class Role(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    APPROVER = "approver"
    ADMIN = "admin"


RANK = {Role.VIEWER: 0, Role.OPERATOR: 1, Role.APPROVER: 2, Role.ADMIN: 3}


def highest(roles: list[str] | tuple[str, ...]) -> Role:
    known = [Role(r) for r in roles if r in Role.__members__.values()]
    return max(known, key=RANK.__getitem__, default=Role.VIEWER)


def has_role(roles: list[str] | tuple[str, ...], needed: Role) -> bool:
    return RANK[highest(roles)] >= RANK[needed]


Code = Literal["forbidden", "invalid-state-transition", "content-hash-mismatch", "conflict"]


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    reason: str = ""
    code: Code | None = None  # maps to the problem type: forbidden → 403, others → 409


ALLOW = Decision(True)


def _deny(code: Code, reason: str) -> Decision:
    return Decision(False, reason, code)


@dataclass(frozen=True, slots=True)
class StrategyFacts:
    status: str
    content_hash: str
    incident_status: str
    planned_by: str  # the human who triggered the planning round
    sibling_statuses: tuple[str, ...]  # other strategies of the same incident (all rounds)


def decide_approval(
    *,
    actor: str,
    roles: list[str] | tuple[str, ...],
    facts: StrategyFacts,
    submitted_hash: str,
    decision: Literal["APPROVE", "REJECT"],
    comment: str | None,
    separation_of_duties: bool,
) -> Decision:
    if not has_role(roles, Role.APPROVER):
        return _deny("forbidden", "Approving or rejecting strategies requires the approver role.")
    if separation_of_duties and actor == facts.planned_by:
        return _deny(
            "forbidden",
            "Separation of duties: the person who requested this plan cannot approve or reject it.",
        )
    if facts.status != StrategyStatus.VALIDATED:
        return _deny(
            "invalid-state-transition",
            f"Strategy is {facts.status}; only VALIDATED strategies can be approved or rejected.",
        )
    if facts.incident_status not in RECOVERABLE:
        return _deny(
            "invalid-state-transition",
            f"Incident is {facts.incident_status}; it is not awaiting a recovery decision.",
        )
    if submitted_hash != facts.content_hash:
        return _deny(
            "content-hash-mismatch",
            "The strategy changed since you reviewed it (content hash differs). Reload and review.",
        )
    if decision == "REJECT" and not (comment and comment.strip()):
        return _deny("conflict", "A rejection needs a comment explaining why.")
    busy = {StrategyStatus.APPROVED, StrategyStatus.EXECUTING, StrategyStatus.EXECUTED,
            StrategyStatus.VERIFIED}  # fmt: skip
    if decision == "APPROVE" and any(s in busy for s in facts.sibling_statuses):
        return _deny(
            "conflict",
            "Another strategy for this incident is already approved or executed.",
        )
    return ALLOW


def decide_execution(*, roles: list[str] | tuple[str, ...], facts: StrategyFacts) -> Decision:
    """Checks that do not need the plan itself; GUARDIAN revalidation (V-001…V-012) follows."""
    if not has_role(roles, Role.OPERATOR):
        return _deny("forbidden", "Executing strategies requires the operator role.")
    if facts.status != StrategyStatus.APPROVED:
        return _deny(
            "invalid-state-transition",
            f"Strategy is {facts.status}; only APPROVED strategies can be executed.",
        )
    return ALLOW
