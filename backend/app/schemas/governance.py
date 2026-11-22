"""Auth, approval, execution, verification and report contracts (Phase 5)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.governance.rules.validator import ValidationReport
from app.governance.rules.verification import VerificationResult

_STRICT = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ auth
class LoginIn(BaseModel):
    model_config = _STRICT
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PrincipalOut(BaseModel):
    username: str
    display_name: str
    roles: list[str]
    role: str = Field(description="highest role (viewer < operator < approver < admin)")


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 — the OAuth token type, not a secret
    expires_at: datetime
    user: PrincipalOut


class GovernanceConfig(BaseModel):
    separation_of_duties: bool


class MeOut(PrincipalOut):
    governance: GovernanceConfig


# ------------------------------------------------------------------ decisions
class ApproveIn(BaseModel):
    model_config = _STRICT
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_version: int = Field(ge=1)
    comment: str | None = Field(default=None, max_length=2000)


class RejectIn(BaseModel):
    model_config = _STRICT
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_version: int = Field(ge=1)
    comment: str = Field(min_length=3, max_length=2000)


class ApprovalOut(BaseModel):
    id: uuid.UUID
    strategy_id: uuid.UUID
    decision: Literal["APPROVED", "REJECTED"]
    content_hash: str
    actor_id: str
    actor_role: str
    comment: str | None
    created_at: datetime


# ------------------------------------------------------------------ execution & verification
class VerificationOut(BaseModel):
    id: uuid.UUID
    execution_id: uuid.UUID
    verified_by: str
    created_at: datetime
    result: VerificationResult
    synthetic: Literal[True] = True


class RecoveryExecutionOut(BaseModel):
    id: uuid.UUID
    strategy_id: uuid.UUID
    incident_id: uuid.UUID
    simulation_run_id: uuid.UUID | None
    approval_id: uuid.UUID
    requested_by: str
    status: Literal["COMPLETED", "FAILED"]
    revalidation: ValidationReport
    error: dict[str, str] | None
    started_at: datetime
    completed_at: datetime | None
    verification: VerificationOut | None
    replayed: bool = Field(
        default=False, description="true when this response repeats an earlier request"
    )
    synthetic: Literal[True] = True


class CloseIncidentIn(BaseModel):
    model_config = _STRICT
    reason: str = Field(min_length=3, max_length=500)


class ChainVerificationOut(BaseModel):
    ok: bool
    records_checked: int
    first_broken_id: int | None
