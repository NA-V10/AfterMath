"use client";

import { Wand2 } from "lucide-react";
import { useState } from "react";

import { Badge, ErrorState, Loading, Panel, cn } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { formatMinutes, formatNumber } from "@/lib/domain";
import { useGenerateStrategies, useIncidents, useStrategyRound } from "@/lib/queries";

import { POLICY_COLOR, POLICY_LABEL, StrategyChart } from "./StrategyChart";
import { StrategyDetailView } from "./StrategyDetailView";

const PLANNABLE = new Set(["ANALYZED", "AWAITING_APPROVAL", "REPORTED"]);

function Comparison({ incidentId }: { incidentId: string }) {
  const round = useStrategyRound(incidentId);
  const generate = useGenerateStrategies();
  const [selected, setSelected] = useState<string | null>(null);

  const notPlanned = round.isError && round.error instanceof ApiError && round.error.status === 404;
  if (round.isPending) return <Loading label="Loading strategies" />;
  if (notPlanned || generate.isPending) {
    return (
      <div className="flex flex-col items-start gap-2 p-6">
        <p className="text-muted">No recovery strategies have been generated for this incident yet.</p>
        <button type="button" disabled={generate.isPending} onClick={() => generate.mutate(incidentId)}
          className="flex items-center gap-1.5 rounded-sm bg-focus px-3 py-1.5 font-medium text-bg disabled:opacity-40">
          <Wand2 className="size-3.5" /> {generate.isPending ? "Planning…" : "Generate strategies"}
        </button>
        {generate.isError && <ErrorState error={generate.error} />}
      </div>
    );
  }
  if (round.isError) return <ErrorState error={round.error} onRetry={() => round.refetch()} />;
  const r = round.data;
  const shown = r.strategies.find((s) => s.id === selected) ?? r.strategies.find((s) => s.recommended) ?? r.strategies[0];

  return (
    <div className="flex flex-col gap-px bg-line" data-testid="strategy-round">
      <div className="flex flex-wrap items-center justify-between gap-2 bg-panel px-3 py-2">
        <span className="text-[12px]">
          Planning round {r.planning_round} · no-action baseline{" "}
          <span className="font-mono">{r.baseline_impact_hours.toFixed(1)}</span> impact-hours
        </span>
        <button type="button" disabled={generate.isPending} onClick={() => generate.mutate(incidentId)}
          className="rounded-sm border border-line-strong px-2 py-0.5 text-[11px] hover:bg-raised">
          Re-plan with current inventory
        </button>
      </div>
      <div className="grid gap-px bg-line md:grid-cols-3">
        {r.strategies.map((s) => (
          <button key={s.id} type="button" onClick={() => setSelected(s.id)} data-testid={`strategy-card-${s.policy}`}
            aria-pressed={shown?.id === s.id}
            className={cn("flex flex-col gap-1.5 bg-panel p-3 text-left hover:bg-raised", shown?.id === s.id && "bg-raised outline outline-1 outline-focus")}>
            <span className="flex items-center gap-1.5">
              <span className="size-2.5 rounded-full" style={{ background: POLICY_COLOR[s.policy] }} />
              <span className="font-medium">{POLICY_LABEL[s.policy]}</span>
              {s.recommended && <Badge color="#58a6ff">recommended</Badge>}
              <Badge color={s.status === "VALIDATED" ? "#3fb950" : "#f85149"}>{s.status === "VALIDATED" ? "valid" : s.status.toLowerCase()}</Badge>
            </span>
            <span className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px]">
              <span className="text-dim">Impact</span><span className="text-right font-mono">{s.impact_hours.toFixed(1)} ih</span>
              <span className="text-dim">Critical services</span>
              <span className="text-right font-mono">{s.time_to_critical_services_minutes == null ? "—" : formatMinutes(s.time_to_critical_services_minutes)}</span>
              <span className="text-dim">90% operational</span>
              <span className="text-right font-mono">{s.time_to_90pct_operational_minutes == null ? "—" : formatMinutes(s.time_to_90pct_operational_minutes)}</span>
              <span className="text-dim">All repairs done</span><span className="text-right font-mono">{formatMinutes(s.makespan_minutes)}</span>
              <span className="text-dim">Cost</span><span className="text-right font-mono">{formatNumber(s.total_cost)}</span>
              <span className="text-dim">Risk</span><span className="text-right font-mono">{s.risk_score.toFixed(1)}</span>
            </span>
            {s.identical_to.length > 0 && <span className="text-[11px] text-focus">Same plan as {s.identical_to.map((p) => POLICY_LABEL[p]).join(", ")}</span>}
          </button>
        ))}
      </div>
      <div className="h-64 bg-panel"><StrategyChart round={r} /></div>
      <div className="bg-bg">{shown && <StrategyDetailView s={shown} />}</div>
    </div>
  );
}

export function RecoveryCommand() {
  const incidents = useIncidents();
  const [incidentId, setIncidentId] = useState<string | null>(null);
  const plannable = (incidents.data?.items ?? []).filter((i) => PLANNABLE.has(i.status) && i.analysis_available);
  const effective = incidentId ?? plannable.find((i) => i.status === "AWAITING_APPROVAL")?.id ?? null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-1.5">
        <h1 className="text-[13px] font-semibold">Recovery Command</h1>
        <span className="text-[11px] text-dim">Plans are computed and validated deterministically · ih = impact-hours</span>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-px bg-line lg:grid-cols-[260px_minmax(0,1fr)]">
        <Panel title="Incidents" className="border-0" bodyClassName="overflow-y-auto">
          {incidents.isPending ? <Loading /> : incidents.isError ? <ErrorState error={incidents.error} /> : (
            <ul aria-label="Plannable incidents">
              {plannable.map((i) => (
                <li key={i.id}>
                  <button type="button" onClick={() => setIncidentId(i.id)}
                    className={cn("w-full border-b border-line px-3 py-1.5 text-left hover:bg-raised", effective === i.id && "bg-raised")}>
                    <span className="flex items-center justify-between gap-2">
                      <span className="font-mono text-[12px]">{i.reference}</span>
                      <span className="text-[10px] text-dim">{i.status.replaceAll("_", " ").toLowerCase()}</span>
                    </span>
                    <span className="block truncate text-[11px] text-muted">{i.title ?? i.raw_report}</span>
                  </button>
                </li>
              ))}
              {plannable.length === 0 && (
                <li className="p-3 text-muted">No analysed incidents. Report one in Agent Activity; the agents plan recovery automatically.</li>
              )}
            </ul>
          )}
        </Panel>
        <div className="min-h-0 overflow-y-auto bg-bg">
          {effective ? <Comparison key={effective} incidentId={effective} /> : (
            <p className="mx-auto max-w-lg p-8 text-center text-muted">Select an analysed incident to compare its recovery strategies.</p>
          )}
        </div>
      </div>
    </div>
  );
}
