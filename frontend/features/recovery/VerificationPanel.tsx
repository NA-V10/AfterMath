"use client";

import { AlertTriangle, CheckCircle2 } from "lucide-react";

import { SectionLabel, Stat } from "@/components/ui/primitives";
import type { Execution } from "@/lib/queries";

function Delta({ label, before, after }: { label: string; before: number; after: number }) {
  return (
    <div className="flex flex-col rounded-md border border-line-strong bg-panel-2 px-3 py-2">
      <span className="text-[13px] text-dim">{label}</span>
      <span className="font-mono text-[13px]">
        <span className="text-muted">{before.toFixed(1)}%</span> → <span className="font-medium">{after.toFixed(1)}%</span>
      </span>
    </div>
  );
}

/** GUARDIAN's verification of a simulated execution: repaired vs functionally restored. */
export function VerificationPanel({ execution }: { execution: Execution }) {
  const v = execution.verification?.result;
  if (!v) return <p className="text-[14px] text-warn">Execution {execution.status.toLowerCase()} without verification.</p>;
  const full = v.outcome === "FULLY_RESTORED";
  return (
    <section className="flex flex-col gap-2.5 rounded-lg border border-line-strong p-3.5" data-testid="verification">
      <div className="flex flex-wrap items-center gap-2">
        {full ? <CheckCircle2 className="size-4 text-ok" aria-hidden /> : <AlertTriangle className="size-4 text-warn" aria-hidden />}
        <span className="font-medium" data-testid="verification-outcome">
          {full ? "Fully restored" : "Partially restored"}
        </span>
        <span className="text-[13px] text-dim">
          simulated execution by <span className="font-mono">{execution.requested_by}</span> · verified by GUARDIAN
        </span>
      </div>
      <p className={v.matches_expectation ? "text-[14px] text-ok" : "text-[14px] font-medium text-crit"}>
        {v.matches_expectation
          ? "The outcome matches the approved plan's expectation exactly (same result hash)."
          : "The outcome differs from the approved plan's expectation. This indicates a defect and has been logged."}
      </p>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <Delta label="Assets operational" before={v.before.by_count} after={v.after.by_count} />
        <Delta label="Criticality-weighted" before={v.before.by_criticality} after={v.after.by_criticality} />
        <Delta label="Population served" before={v.before.by_population} after={v.after.by_population} />
      </div>
      <p className="text-[13px] text-dim">
        “Before” is the same incident with no recovery at the same horizon (T+{Math.round(v.horizon_minutes / 60)}h).
      </p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Impact before" value={v.impact_score_before.toFixed(1)} />
        <Stat label="Impact after" value={v.impact_score_after.toFixed(1)} />
        <Stat label="Repaired" value={String(v.repaired_assets.length)} />
        <Stat label="Restored to service" value={String(v.functionally_restored.length)} />
      </div>
      {v.repaired_not_functional.length > 0 && (
        <div>
          <SectionLabel>Repaired but not functional</SectionLabel>
          <ul className="text-[14px] text-warn">
            {v.repaired_not_functional.map((u) => (
              <li key={u.code}>
                <span className="font-mono">{u.code}</span> {u.name}: {u.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div>
        <SectionLabel>{`Still not operational (${v.unresolved.length})`}</SectionLabel>
        {v.unresolved.length === 0 ? (
          <p className="text-[14px] text-dim">None.</p>
        ) : (
          <table className="w-full text-left text-[13px]">
            <tbody>
              {v.unresolved.map((u) => (
                <tr key={u.code} className="border-t border-line">
                  <td className="py-0.5 pr-2 font-mono">{u.code}</td>
                  <td className="pr-2">{u.name}</td>
                  <td className="pr-2 text-muted">{u.status.replace("_", " ").toLowerCase()}</td>
                  <td className="text-dim">{u.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
