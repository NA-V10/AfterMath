"""P11/P12 as a stateful property over the real API.

Hypothesis drives random sequences of approve / reject / execute / tamper / re-plan calls by
different users against one incident and checks every response against a simple model:

- P11: unapproved, rejected, validation-failed or superseded strategies never execute;
- P12: a content change after approval blocks execution;
- at most one strategy per incident is ever executed, and only with a matching approval.

The machine runs in a worker thread; each API call is scheduled on the test's event loop.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from httpx import AsyncClient
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule, run_state_machine_as_test
from sqlalchemy import text

from app.database.session import Database
from tests.conftest import DATASET_DIR

RIVERSIDE = {
    "source": "STRUCTURED", "title": "Stateful governance", "incident_type": "POWER_FAILURE",
    "severity": "HIGH", "initiating_events": [{"kind": "ASSET_FAILURE", "asset_code": "SUB-02"}],
}  # fmt: skip
SEED = json.loads((DATASET_DIR / "inventory.json").read_text(encoding="utf-8"))
REQUESTER = "test-operator"
APPROVERS = {"test-approver", "test-approver2", "test-admin"}
OPERATORS = {"test-operator", "test-operator2", "test-approver", "test-approver2", "test-admin"}
SUPERSEDABLE = {"DRAFT", "VALIDATED", "APPROVED"}
DONE = {"EXECUTED", "VERIFIED"}


def build_machine(
    call: Callable[[Coroutine[Any, Any, Any]], Any],
    clients: dict[str, AsyncClient],
    database: Database,
) -> type[RuleBasedStateMachine]:
    def api(who: str, method: str, path: str, **kw: Any) -> Any:
        return call(clients[who].request(method, path, **kw))

    class Governance(RuleBasedStateMachine):
        def __init__(self) -> None:
            super().__init__()
            r = api("test-admin", "POST", "/inventory", json={
                "renewables": SEED["renewables"], "consumables": SEED["consumables"],
                "reason": "stateful restock",
            })  # fmt: skip
            assert r.status_code == 201
            self.incident = api(REQUESTER, "POST", "/incidents", json=RIVERSIDE).json()["id"]
            self.status: dict[str, str] = {}
            self.tampered: set[str] = set()
            self.incident_status = "AWAITING_APPROVAL"
            self._plan()

        # ---------------------------------------------------------- helpers
        def _plan(self) -> int:
            r = api(REQUESTER, "POST", "/recovery/strategies", json={"incident_id": self.incident})
            if r.status_code == 201:
                for sid, st_ in self.status.items():
                    if st_ in SUPERSEDABLE:
                        self.status[sid] = "SUPERSEDED"
                for s in r.json()["strategies"]:
                    self.status[s["id"]] = s["status"]
                self.incident_status = "AWAITING_APPROVAL"
            return int(r.status_code)

        def _pick(self, i: int) -> str:
            ids = sorted(self.status)
            return ids[i % len(ids)]

        def _fresh(self, sid: str) -> dict[str, Any]:
            r = api("test-viewer", "GET", f"/recovery/strategies/{sid}")
            assert r.status_code == 200
            return r.json()  # type: ignore[no-any-return]

        def _busy_sibling(self, sid: str) -> bool:
            return any(s in {"APPROVED"} | DONE for other, s in self.status.items() if other != sid)

        def _recoverable(self) -> bool:
            return self.incident_status in {"ANALYZED", "AWAITING_APPROVAL"}

        # ---------------------------------------------------------- rules
        @rule(i=st.integers(0, 8), who=st.sampled_from(sorted(APPROVERS | {"test-operator"})))
        def approve(self, i: int, who: str) -> None:
            sid = self._pick(i)
            s = self._fresh(sid)
            r = api(who, "POST", f"/recovery/strategies/{sid}/approve", json={
                "content_hash": s["content_hash"], "expected_version": s["version"],
            })  # fmt: skip
            allowed = (
                self.status[sid] == "VALIDATED" and who in APPROVERS and who != REQUESTER
                and not self._busy_sibling(sid) and self._recoverable()
            )  # fmt: skip
            assert (r.status_code == 201) == allowed, (who, self.status[sid], r.text)
            if allowed:
                self.status[sid] = "APPROVED"

        @rule(i=st.integers(0, 8), who=st.sampled_from(sorted(APPROVERS | {"test-operator"})))
        def reject(self, i: int, who: str) -> None:
            sid = self._pick(i)
            s = self._fresh(sid)
            r = api(who, "POST", f"/recovery/strategies/{sid}/reject", json={
                "content_hash": s["content_hash"], "expected_version": s["version"],
                "comment": "Not acceptable.",
            })  # fmt: skip
            allowed = (
                self.status[sid] == "VALIDATED" and who in APPROVERS and who != REQUESTER
                and self._recoverable()
            )  # fmt: skip
            assert (r.status_code == 201) == allowed, (who, self.status[sid], r.text)
            if allowed:
                self.status[sid] = "REJECTED"
                live = [v for v in self.status.values() if v in {"VALIDATED", "APPROVED"}]
                if not live and self.incident_status == "AWAITING_APPROVAL":
                    self.incident_status = "ANALYZED"

        @rule(i=st.integers(0, 8), who=st.sampled_from(["test-operator", "test-viewer"]))
        def execute(self, i: int, who: str) -> None:
            sid = self._pick(i)
            r = api(who, "POST", f"/recovery/strategies/{sid}/execute",
                    headers={"Idempotency-Key": f"sm-{uuid.uuid4()}"})  # fmt: skip
            approved = self.status[sid] == "APPROVED"
            if who not in OPERATORS:
                assert r.status_code == 403, r.text
                return
            if approved and sid not in self.tampered:
                assert r.status_code == 201, r.text
                assert r.json()["verification"]["result"]["matches_expectation"] is True
                self.status[sid] = "VERIFIED"
                for other, s in self.status.items():
                    if other != sid and s in SUPERSEDABLE:
                        self.status[other] = "SUPERSEDED"
                self.incident_status = "RECOVERED"
            else:
                assert r.status_code == 409, (self.status[sid], r.text)  # P11 / P12
                if approved:  # tampered after approval: revalidation fails, permanently
                    assert r.json()["type"].endswith("/revalidation-failed")
                    self.status[sid] = "VALIDATION_FAILED"

        @rule(i=st.integers(0, 8))
        def tamper(self, i: int) -> None:
            sid = self._pick(i)

            async def go() -> int:
                async with database.sessionmaker() as s:
                    res = await s.execute(
                        text("UPDATE recovery_action SET start_minutes = start_minutes + 7, "
                             "end_minutes = end_minutes + 7 WHERE strategy_id = :s"),
                        {"s": sid},
                    )  # fmt: skip
                    await s.commit()
                    return int(res.rowcount)  # type: ignore[attr-defined]

            if call(go()) > 0:
                self.tampered.add(sid)

        @rule()
        def replan(self) -> None:
            code = self._plan()
            assert (code == 201) == (self.incident_status not in {"RECOVERED", "CLOSED"}), code

        # ---------------------------------------------------------- invariants
        @invariant()
        def api_agrees_with_model(self) -> None:
            r = api("test-viewer", "GET", "/recovery/strategies",
                    params={"incident_id": self.incident})  # fmt: skip
            actual = {s["id"]: s["status"] for s in r.json()}
            assert actual == self.status

        @invariant()
        def at_most_one_execution_and_only_when_approved(self) -> None:
            done = [sid for sid, s in self.status.items() if s in DONE]
            assert len(done) <= 1
            for sid in done:
                d = self._fresh(sid)
                approvals = [x for x in d["decisions"] if x["decision"] == "APPROVED"]
                assert approvals
                assert approvals[-1]["content_hash"] == d["content_hash"]
                assert sid not in self.tampered

    return Governance


async def test_p11_p12_governance_state_machine(
    clients: dict[str, AsyncClient], database: Database
) -> None:
    loop = asyncio.get_running_loop()

    def call(coro: Coroutine[Any, Any, Any]) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=120)

    machine = build_machine(call, clients, database)
    await asyncio.to_thread(
        run_state_machine_as_test,
        machine,
        settings=settings(
            max_examples=12,
            stateful_step_count=10,
            deadline=None,
            database=None,
            suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
        ),
    )
    chain = (await clients["test-viewer"].get("/audit/verify-chain")).json()
    assert chain["ok"] is True  # P14 after an arbitrary sequence of operations
