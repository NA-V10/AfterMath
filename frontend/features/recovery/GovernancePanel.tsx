"use client";

import { CheckCircle2, Gavel, Play, ShieldCheck, XCircle } from "lucide-react";
import { useState } from "react";

import { ErrorState, SectionLabel } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { type StrategyDetail, useDecide, useExecute, useExecution, useMe } from "@/lib/queries";
import { hasRole, useSession } from "@/lib/session";

import { VerificationPanel } from "./VerificationPanel";

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });

function Decisions({ s }: { s: StrategyDetail }) {
  if (s.decisions.length === 0) return <p className="text-[14px] text-dim">No decision has been recorded.</p>;
  return (
    <ul className="flex flex-col gap-1 text-[14px]" data-testid="decisions">
      {s.decisions.map((d) => (
        <li key={d.id} className="flex items-start gap-1.5">
          {d.decision === "APPROVED" ? (
            <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-ok" aria-hidden />
          ) : (
            <XCircle className="mt-0.5 size-3.5 shrink-0 text-crit" aria-hidden />
          )}
          <span>
            <span className="font-medium">{d.decision === "APPROVED" ? "Approved" : "Rejected"}</span> by{" "}
            <span className="font-mono">{d.actor_id}</span> ({d.actor_role}) · {when(d.created_at)} · hash{" "}
            <span className="font-mono">{d.content_hash.slice(0, 10)}…</span>
            {d.comment && <span className="block text-muted">“{d.comment}”</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

function problemOf(error: unknown): string | null {
  if (!(error instanceof ApiError) || !error.problem) return null;
  return error.problem.type.split("/").at(-1) ?? null;
}

/** Approve / reject (approver) and simulated execution (operator) for one strategy. */
export function GovernancePanel({ s, incidentId }: { s: StrategyDetail; incidentId: string }) {
  const session = useSession();
  const me = useMe(!!session);
  const approve = useDecide(incidentId, "approve");
  const reject = useDecide(incidentId, "reject");
  const execute = useExecute(incidentId);
  const execution = useExecution(s.execution_id);
  const [comment, setComment] = useState("");
  // One key per strategy view: a double click or a retry after a network error is not run twice.
  const [idempotencyKey] = useState(() => `ui-${crypto.randomUUID()}`);
  const [confirming, setConfirming] = useState(false);

  const isApprover = hasRole(session, "approver");
  const isOperator = hasRole(session, "operator");
  const sod = me.data?.governance.separation_of_duties ?? true;
  const ownPlan = sod && session?.user.username === s.requested_by;
  const decision = { strategyId: s.id, contentHash: s.content_hash, version: s.version, comment };
  const busy = approve.isPending || reject.isPending || execute.isPending;
  const error = approve.error ?? reject.error ?? execute.error;

  return (
    <div className="flex flex-col gap-3" data-testid="governance-panel">
      <div>
        <SectionLabel>Decisions</SectionLabel>
        <Decisions s={s} />
      </div>

      {s.status === "VALIDATED" && (
        <div className="flex flex-col gap-2.5 rounded-lg border border-line-strong p-3.5">
          <span className="flex items-center gap-1.5 text-[14px] font-medium">
            <Gavel className="size-3.5" aria-hidden /> Human decision required
          </span>
          {!isApprover ? (
            <p className="text-[14px] text-muted">Only an approver can approve or reject this strategy.</p>
          ) : ownPlan ? (
            <p className="text-[14px] text-warn" data-testid="sod-notice">
              You requested this plan. Separation of duties: another approver must decide.
            </p>
          ) : (
            <>
              <p className="text-[13px] text-dim">
                You are deciding on exactly this content (hash {s.content_hash.slice(0, 10)}…, version {s.version}). If it
                changes, your decision is refused and you review again.
              </p>
              <label className="flex flex-col gap-1 text-[14px]">
                Comment <span className="text-[13px] text-dim">(required to reject)</span>
                <textarea
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  rows={2}
                  maxLength={2000}
                  aria-label="Decision comment"
                  className="field"
                />
              </label>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => approve.mutate(decision)}
                  className="btn btn-primary"
                >
                  <CheckCircle2 className="size-3.5" aria-hidden /> Approve
                </button>
                <button
                  type="button"
                  disabled={busy || comment.trim().length < 3}
                  onClick={() => reject.mutate(decision)}
                  title={comment.trim().length < 3 ? "Explain the rejection in the comment" : undefined}
                  className="btn btn-secondary"
                >
                  <XCircle className="size-3.5" aria-hidden /> Reject
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {s.status === "APPROVED" && (
        <div className="flex flex-col gap-2.5 rounded-lg border border-ok/40 bg-ok/5 p-3.5">
          <span className="flex items-center gap-1.5 text-[14px] font-medium">
            <ShieldCheck className="size-3.5 text-ok" aria-hidden /> Approved — ready for simulated execution
          </span>
          <p className="text-[13px] text-dim">
            GUARDIAN revalidates the plan against the current twin and inventory (V-001…V-012) first. Execution replays the
            plan in the simulator and applies the result to the operational picture. Nothing leaves the simulation.
          </p>
          {!isOperator ? (
            <p className="text-[14px] text-muted">Only an operator can execute.</p>
          ) : !confirming ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => setConfirming(true)}
              className="btn btn-primary self-start"
            >
              <Play className="size-3.5" aria-hidden /> Execute (simulated)
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-[14px]">Run this approved plan now?</span>
              <button
                type="button"
                disabled={busy}
                onClick={() => execute.mutate({ strategyId: s.id, idempotencyKey })}
                className="btn btn-primary"
              >
                {execute.isPending ? "Executing…" : "Confirm execution"}
              </button>
              <button type="button" disabled={busy} onClick={() => setConfirming(false)} className="text-[14px] text-muted">
                Cancel
              </button>
            </div>
          )}
        </div>
      )}

      {["REJECTED", "SUPERSEDED", "VALIDATION_FAILED", "EXECUTION_FAILED"].includes(s.status) && (
        <p className="text-[14px] text-muted" data-testid="not-executable">
          This strategy is {s.status.replaceAll("_", " ").toLowerCase()} and can never be executed.
        </p>
      )}

      {error && (
        <div>
          <ErrorState error={error} />
          {problemOf(error) === "revalidation-failed" && (
            <p className="mt-1 text-[13px] text-dim">The GUARDIAN rule list below shows what failed. Re-plan the incident.</p>
          )}
        </div>
      )}

      {s.execution_id &&
        (execution.isPending ? (
          <p className="text-dim">Loading verification…</p>
        ) : execution.isError ? (
          <ErrorState error={execution.error} />
        ) : (
          <VerificationPanel execution={execution.data} />
        ))}
    </div>
  );
}
