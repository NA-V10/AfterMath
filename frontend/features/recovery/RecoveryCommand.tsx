"use client";

import { Download, Lock, Wand2 } from "lucide-react";
import { useState } from "react";

import { Badge, ErrorState, Loading, Panel, cn } from "@/components/ui/primitives";
import { API_ORIGIN, ApiError, authHeaders, type Schemas } from "@/lib/api";
import { formatMinutes, formatNumber } from "@/lib/domain";
import { useCloseIncident, useGenerateStrategies, useIncidents, useStrategyRound } from "@/lib/queries";
import { hasRole, useSession } from "@/lib/session";

import { strategyStatus } from "./status";
import { POLICY_COLOR, POLICY_LABEL, StrategyChart } from "./StrategyChart";
import { StrategyDetailView } from "./StrategyDetailView";

type Incident = Schemas["IncidentOut"];

const VISIBLE = new Set(["REPORTED", "ANALYZED", "AWAITING_APPROVAL", "RECOVERED", "CLOSED"]);
const PLANNABLE = new Set(["REPORTED", "ANALYZED", "AWAITING_APPROVAL"]);
const DECIDED = ["VERIFIED", "EXECUTED", "APPROVED"];

async function downloadReport(incident: Incident): Promise<void> {
  const res = await fetch(`${API_ORIGIN}/api/v1/reports/incidents/${incident.id}?format=markdown`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Report download failed (${res.status}).`);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = `${incident.reference}-report.md`;
  a.click();
  URL.revokeObjectURL(url);
}

function IncidentHeader({ incident }: { incident: Incident }) {
  const session = useSession();
  const close = useCloseIncident(incident.id);
  const [closing, setClosing] = useState(false);
  const [reason, setReason] = useState("");
  const [reportError, setReportError] = useState<Error | null>(null);
  return (
    <div className="flex flex-col gap-1.5 bg-panel px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono font-semibold">{incident.reference}</span>
        <span className="text-[12px]">{incident.title ?? incident.raw_report}</span>
        <Badge>
          <span data-testid="incident-status">{incident.status.replaceAll("_", " ").toLowerCase()}</span>
        </Badge>
        <span className="flex-1" />
        <button
          type="button"
          onClick={() => downloadReport(incident).catch((e: Error) => setReportError(e))}
          className="flex items-center gap-1 rounded-sm border border-line-strong px-2 py-0.5 text-[11px] hover:bg-raised"
        >
          <Download className="size-3" aria-hidden /> Report (Markdown)
        </button>
        {hasRole(session, "operator") && incident.status !== "CLOSED" && (
          <button
            type="button"
            onClick={() => setClosing((c) => !c)}
            className="flex items-center gap-1 rounded-sm border border-line-strong px-2 py-0.5 text-[11px] hover:bg-raised"
          >
            <Lock className="size-3" aria-hidden /> Close incident
          </button>
        )}
      </div>
      {closing && (
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason for closing"
            aria-label="Reason for closing"
            className="min-w-64 flex-1 rounded-sm border border-line-strong bg-bg px-2 py-0.5 text-[12px]"
          />
          <button
            type="button"
            disabled={reason.trim().length < 3 || close.isPending}
            onClick={() => close.mutate(reason.trim(), { onSuccess: () => setClosing(false) })}
            className="rounded-sm bg-focus px-2 py-0.5 text-[11px] font-medium text-bg disabled:opacity-40"
          >
            Confirm close
          </button>
          <span className="text-[11px] text-dim">Open strategies are superseded.</span>
        </div>
      )}
      {close.isError && <ErrorState error={close.error} />}
      {reportError && <ErrorState error={reportError} />}
    </div>
  );
}

function Comparison({ incident }: { incident: Incident }) {
  const session = useSession();
  const round = useStrategyRound(incident.id);
  const generate = useGenerateStrategies();
  const [selected, setSelected] = useState<string | null>(null);
  const canPlan = hasRole(session, "operator") && PLANNABLE.has(incident.status) && incident.analysis_available;

  const notPlanned = round.isError && round.error instanceof ApiError && round.error.status === 404;
  if (round.isPending) return <Loading label="Loading strategies" />;
  if (notPlanned || generate.isPending) {
    return (
      <div className="flex flex-col items-start gap-2 p-6">
        <p className="text-muted">No recovery strategies have been generated for this incident yet.</p>
        {canPlan ? (
          <button type="button" disabled={generate.isPending} onClick={() => generate.mutate(incident.id)}
            className="flex items-center gap-1.5 rounded-sm bg-focus px-3 py-1.5 font-medium text-bg disabled:opacity-40">
            <Wand2 className="size-3.5" /> {generate.isPending ? "Planning…" : "Generate strategies"}
          </button>
        ) : (
          <p className="text-[12px] text-dim">An operator can generate strategies for analysed incidents.</p>
        )}
        {generate.isError && <ErrorState error={generate.error} />}
      </div>
    );
  }
  if (round.isError) return <ErrorState error={round.error} onRetry={() => round.refetch()} />;
  const r = round.data;
  const shown =
    r.strategies.find((s) => s.id === selected) ??
    r.strategies.find((s) => DECIDED.includes(s.status)) ??
    r.strategies.find((s) => s.recommended) ??
    r.strategies[0];

  return (
    <div className="flex flex-col gap-px bg-line" data-testid="strategy-round">
      <div className="flex flex-wrap items-center justify-between gap-2 bg-panel px-3 py-2">
        <span className="text-[12px]">
          Planning round {r.planning_round} · no-action baseline{" "}
          <span className="font-mono">{r.baseline_impact_hours.toFixed(1)}</span> impact-hours
        </span>
        {canPlan && (
          <button type="button" disabled={generate.isPending} onClick={() => generate.mutate(incident.id)}
            title="A new round supersedes the current strategies, including an approval"
            className="rounded-sm border border-line-strong px-2 py-0.5 text-[11px] hover:bg-raised">
            Re-plan with current inventory
          </button>
        )}
      </div>
      <div className="grid gap-px bg-line md:grid-cols-3">
        {r.strategies.map((s) => {
          const st = strategyStatus(s.status);
          return (
            <button key={s.id} type="button" onClick={() => setSelected(s.id)} data-testid={`strategy-card-${s.policy}`}
              data-status={s.status} aria-pressed={shown?.id === s.id}
              className={cn("flex flex-col gap-1.5 bg-panel p-3 text-left hover:bg-raised", shown?.id === s.id && "bg-raised outline outline-1 outline-focus")}>
              <span className="flex flex-wrap items-center gap-1.5">
                <span className="size-2.5 rounded-full" style={{ background: POLICY_COLOR[s.policy] }} />
                <span className="font-medium">{POLICY_LABEL[s.policy]}</span>
                {s.recommended && <Badge color="#58a6ff">recommended</Badge>}
                <Badge color={st.color}>{st.label}</Badge>
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
          );
        })}
      </div>
      <div className="h-64 bg-panel"><StrategyChart round={r} /></div>
      <div className="bg-bg">{shown && <StrategyDetailView s={shown} incidentId={incident.id} />}</div>
    </div>
  );
}

export function RecoveryCommand() {
  const incidents = useIncidents();
  const [incidentId, setIncidentId] = useState<string | null>(null);
  const visible = (incidents.data?.items ?? []).filter((i) => VISIBLE.has(i.status) && i.analysis_available);
  const effectiveId = incidentId ?? visible.find((i) => i.status === "AWAITING_APPROVAL")?.id ?? null;
  const incident = visible.find((i) => i.id === effectiveId) ?? null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-1.5">
        <h1 className="text-[13px] font-semibold">Recovery Command</h1>
        <span className="text-[11px] text-dim">
          Plans are computed and validated deterministically · humans approve · execution is simulated · ih = impact-hours
        </span>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-px bg-line lg:grid-cols-[260px_minmax(0,1fr)]">
        <Panel title="Incidents" className="border-0" bodyClassName="overflow-y-auto">
          {incidents.isPending ? <Loading /> : incidents.isError ? <ErrorState error={incidents.error} /> : (
            <ul aria-label="Incidents with recovery plans">
              {visible.map((i) => (
                <li key={i.id}>
                  <button type="button" onClick={() => setIncidentId(i.id)}
                    className={cn("w-full border-b border-line px-3 py-1.5 text-left hover:bg-raised", effectiveId === i.id && "bg-raised")}>
                    <span className="flex items-center justify-between gap-2">
                      <span className="font-mono text-[12px]">{i.reference}</span>
                      <span className="text-[10px] text-dim">{i.status.replaceAll("_", " ").toLowerCase()}</span>
                    </span>
                    <span className="block truncate text-[11px] text-muted">{i.title ?? i.raw_report}</span>
                  </button>
                </li>
              ))}
              {visible.length === 0 && (
                <li className="p-3 text-muted">No analysed incidents. Report one in Agent Activity; the agents plan recovery automatically.</li>
              )}
            </ul>
          )}
        </Panel>
        <div className="min-h-0 overflow-y-auto bg-bg">
          {incident ? (
            <div className="flex flex-col gap-px bg-line">
              <IncidentHeader incident={incident} />
              <Comparison key={incident.id} incident={incident} />
            </div>
          ) : (
            <p className="mx-auto max-w-lg p-8 text-center text-muted">Select an analysed incident to compare its recovery strategies.</p>
          )}
        </div>
      </div>
    </div>
  );
}
