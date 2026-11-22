"use client";

import { ArrowRight, CircleDashed, Loader2 } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge, ErrorState, Loading, Panel, SectionLabel, cn } from "@/components/ui/primitives";
import type { Schemas } from "@/lib/api";
import {
  type AgentExecution,
  type Workflow,
  useAgents,
  useClarify,
  useGraph,
  useIncidents,
  useWorkflow,
  useWorkflows,
} from "@/lib/queries";
import { hasRole, useSession } from "@/lib/session";

import { ExecutionDetail } from "./ExecutionDetail";
import { IncidentIntake } from "./IncidentIntake";
import { useWorkflowStream } from "./useWorkflowStream";

const STATUS_COLOR: Record<string, string> = {
  SUCCEEDED: "#3fb950",
  FELL_BACK: "#d29922",
  FAILED: "#f85149",
  RUNNING: "#58a6ff",
};

function AgentCard({
  def,
  execution,
  running,
  selected,
  onSelect,
}: {
  def: Schemas["AgentDefinition"];
  execution: AgentExecution | undefined;
  running: boolean;
  selected: boolean;
  onSelect: () => void;
}) {
  const status = !def.available ? "PHASE" : (execution?.status ?? (running ? "PENDING" : "NOT RUN"));
  const color = STATUS_COLOR[status];
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={!execution}
      data-testid={`agent-card-${def.name}`}
      data-status={status}
      className={cn(
        "flex min-w-36 flex-1 flex-col items-start gap-1 rounded-sm border bg-panel-2 p-2 text-left transition-colors",
        selected ? "border-focus" : "border-line-strong",
        !def.available && "opacity-50",
        execution && "hover:bg-raised",
      )}
    >
      <span className="font-mono text-[12px] font-semibold">{def.name}</span>
      <span className="text-[11px] text-muted">{def.role}</span>
      <span className="flex items-center gap-1 text-[11px]" style={{ color }}>
        {status === "RUNNING" && <Loader2 className="size-3 animate-spin" />}
        {status === "PENDING" && <CircleDashed className="size-3 text-dim" />}
        {status === "PHASE" ? `available in Phase ${def.available_from_phase}` : status.replace("_", " ").toLowerCase()}
      </span>
      {execution?.summary && <span className="line-clamp-2 text-[11px] text-dim">{execution.summary}</span>}
    </button>
  );
}

function Clarification({ run }: { run: Workflow }) {
  const graph = useGraph();
  const clarify = useClarify(run.id);
  const q = run.pending_question as {
    message: string;
    missing_information: string[];
    candidates: { code: string; name: string; quote: string; score: number }[];
  } | null;
  const [codes, setCodes] = useState<string[]>(() => q?.candidates.map((c) => c.code) ?? []);
  const assets = (graph.data?.nodes ?? []).filter((n) => n.category !== "DEMAND_ZONE");
  if (!q) return null;
  return (
    <div className="m-3 flex flex-col gap-2 rounded-sm border border-warn/50 bg-warn/5 p-3" data-testid="clarification">
      <div className="font-medium text-warn">Operator input required</div>
      <p className="text-[12px]">{q.message}</p>
      {q.missing_information.length > 0 && (
        <p className="text-[11px] text-muted">Missing: {q.missing_information.join("; ")}</p>
      )}
      <label className="block">
        <SectionLabel>Damaged facilities</SectionLabel>
        <select
          multiple
          value={codes}
          onChange={(e) => setCodes(Array.from(e.target.selectedOptions, (o) => o.value))}
          aria-label="Damaged facilities"
          className="h-32 w-full rounded-sm border border-line-strong bg-bg p-1 text-[12px]"
        >
          {assets.map((a) => (
            <option key={a.code} value={a.code}>
              {a.code} · {a.name}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        disabled={codes.length === 0 || clarify.isPending}
        onClick={() => clarify.mutate({ asset_codes: codes, condition: "DAMAGED" })}
        className="self-start rounded-sm bg-focus px-3 py-1 font-medium text-bg disabled:opacity-40"
      >
        Confirm and continue
      </button>
      {clarify.isError && <ErrorState error={clarify.error} />}
    </div>
  );
}

function WorkflowView({ runId }: { runId: string }) {
  const run = useWorkflow(runId);
  const agents = useAgents();
  const stream = useWorkflowStream(runId, run.data?.status === "RUNNING");
  const [selected, setSelected] = useState<string | null>(null);

  const latest = useMemo(() => {
    const m = new Map<string, AgentExecution>();
    for (const e of run.data?.executions ?? []) m.set(e.agent, e); // later attempts override
    return m;
  }, [run.data]);

  if (run.isPending || agents.isPending) return <Loading label="Loading workflow" />;
  if (run.isError) return <ErrorState error={run.error} onRetry={() => run.refetch()} />;
  if (agents.isError) return <ErrorState error={agents.error} />;
  const r = run.data;
  const shown =
    (selected ? r.executions.find((e) => e.id === selected) : undefined) ??
    [...r.executions].reverse().find((e) => e.status !== "RUNNING") ??
    r.executions.at(-1);

  return (
    <div className="flex flex-col" data-testid="workflow-view">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
        <span className="font-mono font-semibold">{r.incident_reference}</span>
        <Badge color={STATUS_COLOR[r.status === "COMPLETED" ? "SUCCEEDED" : r.status] ?? "#d29922"}>
          <span data-testid="workflow-status">{r.status.replaceAll("_", " ").toLowerCase()}</span>
        </Badge>
        <Badge>{r.llm_mode === "DETERMINISTIC" ? "deterministic mode" : `LLM: ${r.llm_provider}`}</Badge>
        <span className="text-[11px] text-dim">
          {stream === "live" ? "live updates" : r.status === "RUNNING" ? "polling" : ""}
        </span>
      </div>
      <div className="flex flex-wrap items-stretch gap-1 p-3">
        {agents.data.map((def, i) => (
          <div key={def.name} className="flex flex-1 items-center gap-1">
            <AgentCard
              def={def}
              execution={latest.get(def.name)}
              running={r.status === "RUNNING"}
              selected={shown?.agent === def.name}
              onSelect={() => setSelected(latest.get(def.name)?.id ?? null)}
            />
            {i < agents.data.length - 1 && <ArrowRight className="size-3.5 shrink-0 text-dim" aria-hidden />}
          </div>
        ))}
      </div>
      {r.status === "AWAITING_CLARIFICATION" && <Clarification run={r} />}
      {r.error && <ErrorState error={new Error(`${String(r.error.type)}: ${String(r.error.message)}`)} />}
      {shown && <ExecutionDetail execution={shown} />}
    </div>
  );
}

export function AgentActivity() {
  const incidents = useIncidents();
  const [incidentId, setIncidentId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const workflows = useWorkflows(incidentId);
  const effectiveRun = runId ?? workflows.data?.[0]?.id ?? null;
  const canReport = hasRole(useSession(), "operator");

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-1.5">
        <h1 className="text-[13px] font-semibold">Agent Activity</h1>
        <span className="text-[11px] text-dim">Agents interpret and explain · numbers come from deterministic engines · humans decide</span>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-px bg-line lg:grid-cols-[320px_minmax(0,1fr)]">
        <div className="flex min-h-0 flex-col gap-px overflow-y-auto bg-line">
          <Panel title="Report an incident" className="shrink-0 border-0">
            {canReport ? (
              <IncidentIntake
                onStarted={(i, r) => {
                  setIncidentId(i);
                  setRunId(r);
                }}
              />
            ) : (
              <p className="p-3 text-[12px] text-muted">
                Only operators can report incidents and start an analysis. You can follow every analysis below.
              </p>
            )}
          </Panel>
          <Panel title="Incidents" className="min-h-[200px] flex-1 border-0" bodyClassName="overflow-y-auto">
            {incidents.isPending ? (
              <Loading />
            ) : incidents.isError ? (
              <ErrorState error={incidents.error} />
            ) : (
              <ul aria-label="Incidents">
                {incidents.data.items.map((i) => (
                  <li key={i.id}>
                    <button
                      type="button"
                      onClick={() => {
                        setIncidentId(i.id);
                        setRunId(null);
                      }}
                      className={cn("w-full border-b border-line px-3 py-1.5 text-left hover:bg-raised", incidentId === i.id && "bg-raised")}
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="font-mono text-[12px]">{i.reference}</span>
                        <span className="text-[10px] text-dim">{i.status.replaceAll("_", " ").toLowerCase()}</span>
                      </span>
                      <span className="block truncate text-[11px] text-muted">
                        {i.title ?? i.raw_report ?? "—"}
                      </span>
                    </button>
                  </li>
                ))}
                {incidents.data.items.length === 0 && <li className="p-3 text-muted">No incidents yet.</li>}
              </ul>
            )}
          </Panel>
        </div>
        <div className="min-h-0 overflow-y-auto bg-bg">
          {effectiveRun ? (
            <WorkflowView key={effectiveRun} runId={effectiveRun} />
          ) : incidentId && workflows.data?.length === 0 ? (
            <p className="p-6 text-muted">This incident has not been analysed yet.</p>
          ) : (
            <p className="mx-auto max-w-lg p-8 text-center text-muted">
              Report an incident to watch SENTINEL assess it, CARTOGRAPHER trace its dependencies
              and ORACLE simulate the cascade, then STRATEGIST plan recovery strategies and
              GUARDIAN validate them for human approval.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
