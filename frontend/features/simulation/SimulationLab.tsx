"use client";

import type { FeatureCollection } from "geojson";
import { CheckCircle2, ChevronLeft, ChevronRight, Pause, Play, ShieldAlert, XCircle } from "lucide-react";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ErrorState, Loading, Panel, SectionLabel, Segmented, Stat, cn } from "@/components/ui/primitives";
import type { Schemas } from "@/lib/api";
import { SERVICE_LABEL, STATUS, formatMinutes, formatNumber } from "@/lib/domain";
import {
  useApplyPicture,
  useBasemap,
  useGraph,
  useReplay,
  useSimulation,
  useSimulationEvents,
  useSimulations,
} from "@/lib/queries";

import type { Highlight } from "../twin/highlight";
import { ComparisonPanel } from "./ComparisonPanel";
import { EventLog } from "./EventLog";
import { ImpactChart } from "./ImpactChart";
import { buildFrames, lastChangeAt, statusesAt } from "./playback";
import { RunPanel } from "./RunPanel";

const TwinMap = dynamic(() => import("../twin/TwinMap"), { ssr: false, loading: () => <Loading label="Loading map" /> });
const DependencyGraph = dynamic(() => import("../twin/DependencyGraph"), { ssr: false, loading: () => <Loading label="Laying out graph" /> });

type View = "map" | "graph";
const EMPTY = new Set<string>();

function runName(s: Schemas["SimulationSummary"]): string {
  return s.label ?? s.scenario_key ?? (s.incident_id ? "incident" : "custom failures");
}

function History({
  selected,
  compare,
  onSelect,
  onToggleCompare,
}: {
  selected: string | null;
  compare: string[];
  onSelect: (id: string) => void;
  onToggleCompare: (id: string) => void;
}) {
  const runs = useSimulations();
  if (runs.isPending) return <Loading label="Loading history" />;
  if (runs.isError) return <ErrorState error={runs.error} onRetry={() => runs.refetch()} />;
  if (runs.data.items.length === 0) return <p className="p-3 text-muted">No simulations yet.</p>;
  return (
    <ul className="flex flex-col" aria-label="Simulation history" data-testid="run-history">
      {runs.data.items.map((r) => (
        <li key={r.id} className={cn("flex items-start gap-2 border-b border-line px-3 py-1.5", selected === r.id && "bg-raised")}>
          <input
            type="checkbox"
            aria-label={`Compare ${runName(r)}`}
            checked={compare.includes(r.id)}
            disabled={!compare.includes(r.id) && compare.length >= 2}
            onChange={() => onToggleCompare(r.id)}
            className="mt-1 accent-[#58a6ff]"
          />
          <button type="button" onClick={() => onSelect(r.id)} className="min-w-0 flex-1 text-left">
            <span className="block truncate">{runName(r)}</span>
            <span className="block text-[11px] text-dim">
              {r.created_at.slice(11, 19)} · impact{" "}
              <span className="font-mono text-muted">{r.impact_score?.toFixed(1) ?? "—"}</span> · {r.failed_count ?? 0} failed
              {r.status === "FAILED" && <span className="text-crit"> · run failed</span>}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function AssetAtTime({
  code,
  status,
  change,
  finalState,
  onClose,
}: {
  code: string;
  status: Schemas["AssetState"]["status"] | undefined;
  change: Schemas["SimEvent"] | undefined;
  finalState: Schemas["AssetState"] | undefined;
  onClose: () => void;
}) {
  const causes = (change?.details as { causes?: Schemas["Cause"][] } | undefined)?.causes ?? [];
  return (
    <div className="flex flex-col gap-1.5 p-3 text-[12px]" data-testid="asset-at-time">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[14px] font-semibold">{code}</span>
        <button type="button" onClick={onClose} className="text-[11px] text-muted hover:text-fg">clear</button>
      </div>
      {status && (
        <span className="flex items-center gap-1.5">
          <span className="size-2 rounded-full" style={{ background: STATUS[status].color }} />
          {STATUS[status].label} at this moment
        </span>
      )}
      {change ? (
        <>
          <SectionLabel>Why ({formatMinutes(change.t_minutes)}, wave {change.wave})</SectionLabel>
          <ul className="flex flex-col gap-1">
            {causes.length === 0 && <li className="text-dim">Restored: all requirements met.</li>}
            {causes.map((c, i) => (
              <li key={i} className="text-muted">
                {c.kind === "PHYSICAL" && "The asset itself is damaged."}
                {c.kind === "BACKUP" && <>Mains power lost ({c.providers.join(", ")}); running on backup.</>}
                {c.kind === "DEPENDENCY" && (
                  <>Required {SERVICE_LABEL[c.service_type ?? ""] ?? c.service_type} unavailable from {c.providers.join(", ") || "providers"}.</>
                )}
                {c.kind === "SOFT_DEPENDENCY" && (
                  <>Supporting {SERVICE_LABEL[c.service_type ?? ""] ?? c.service_type} lost ({c.providers.join(", ")}).</>
                )}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="text-dim">No status change up to this moment.</p>
      )}
      {finalState?.on_backup && (
        <p className="text-warn">{finalState.backup_remaining_minutes} min of backup left at the horizon.</p>
      )}
    </div>
  );
}

export function SimulationLab() {
  const [runId, setRunId] = useState<string | null>(null);
  const [compare, setCompare] = useState<string[]>([]);
  const [showCompare, setShowCompare] = useState(false);
  // null = the end of the run (default when a run is opened)
  const [frameChoice, setFrameIndex] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [view, setView] = useState<View>("map");
  const [selected, setSelected] = useState<string | null>(null);

  const graph = useGraph();
  const basemap = useBasemap();
  const detail = useSimulation(runId);
  const events = useSimulationEvents(runId);
  const replay = useReplay();
  const apply = useApplyPicture();

  const frames = useMemo(() => buildFrames(events.data ?? []), [events.data]);
  const lastFrame = frames.length - 1;
  const frameIndex = Math.min(frameChoice ?? lastFrame, lastFrame);
  const frame = frames[frameIndex];
  const statuses = useMemo(
    () => (detail.data ? statusesAt(frames, frameIndex, detail.data.final_state) : null),
    [frames, frameIndex, detail.data],
  );
  const changes = useMemo(() => lastChangeAt(frames, frameIndex), [frames, frameIndex]);

  useEffect(() => {
    if (!playing) return;
    const t = setTimeout(() => {
      if (frameIndex >= lastFrame) setPlaying(false);
      else setFrameIndex(frameIndex + 1);
    }, 700);
    return () => clearTimeout(t);
  }, [playing, frameIndex, lastFrame]);

  const select = useCallback((code: string | null) => setSelected(code), []);
  const selectRun = (id: string) => {
    setRunId(id);
    setShowCompare(false);
    setFrameIndex(null);
    setPlaying(false);
    replay.reset();
  };

  const highlight: Highlight = useMemo(
    () => ({ selected, upstream: EMPTY, downstream: EMPTY, visible: null, dimUnrelated: false }),
    [selected],
  );

  const bounds = useMemo(() => {
    const b = (basemap.data as FeatureCollection | undefined)?.features.find((f) => f.properties?.layer === "boundary");
    if (!b || b.geometry.type !== "Polygon") return null;
    const ring = b.geometry.coordinates[0];
    return [
      Math.min(...ring.map((p) => p[0])), Math.min(...ring.map((p) => p[1])),
      Math.max(...ring.map((p) => p[0])), Math.max(...ring.map((p) => p[1])),
    ] as [number, number, number, number];
  }, [basemap.data]);

  const d = detail.data;
  const counts = useMemo(() => {
    const c = { OPERATIONAL: 0, DEGRADED: 0, ON_BACKUP: 0, FAILED: 0 };
    for (const s of statuses?.values() ?? []) c[s] += 1;
    return c;
  }, [statuses]);
  const currentPoint = d?.timeline.filter((p) => p.t_minutes <= frame.t).at(-1);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-1.5">
        <h1 className="text-[13px] font-semibold">Simulation Lab</h1>
        <span className="text-[11px] text-dim">Deterministic engine · results are reproducible by hash</span>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-px bg-line lg:grid-cols-[300px_minmax(0,1fr)]">
        <div className="flex min-h-0 flex-col gap-px overflow-y-auto bg-line">
          <Panel title="Run a simulation" className="border-0" bodyClassName="">
            <RunPanel onRun={selectRun} />
          </Panel>
          <Panel
            title="History"
            className="min-h-[200px] flex-1 border-0"
            bodyClassName="overflow-y-auto"
            actions={
              <button
                type="button"
                disabled={compare.length !== 2}
                onClick={() => setShowCompare(true)}
                className="rounded-sm border border-line-strong px-1.5 text-[11px] disabled:opacity-40"
              >
                Compare ({compare.length}/2)
              </button>
            }
          >
            <History
              selected={runId}
              compare={compare}
              onSelect={selectRun}
              onToggleCompare={(id) =>
                setCompare((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id].slice(-2)))
              }
            />
          </Panel>
        </div>

        <div className="min-h-0 overflow-y-auto bg-bg">
          {showCompare && compare.length === 2 ? (
            <ComparisonPanel a={compare[0]} b={compare[1]} onClose={() => setShowCompare(false)} />
          ) : !runId ? (
            <div className="mx-auto max-w-lg p-8 text-center text-muted">
              Choose a scenario or define failures, then run the simulation. You can replay the
              cascade wave by wave, inspect why each asset changed state, and compare runs.
            </div>
          ) : detail.isPending || events.isPending ? (
            <Loading label="Loading simulation" />
          ) : detail.isError || events.isError ? (
            <ErrorState error={detail.error ?? events.error} />
          ) : d && d.status === "FAILED" ? (
            <ErrorState error={new Error(`The engine failed for this run: ${d.error?.message ?? "unknown error"}`)} />
          ) : d ? (
            <div className="flex flex-col gap-px bg-line" data-testid="simulation-result">
              {/* ---------------------------------------------------------------- metrics */}
              <div className="grid grid-cols-3 gap-3 bg-panel p-3 sm:grid-cols-6">
                <Stat label="Impact at moment" value={currentPoint?.impact_score.toFixed(2) ?? "0.00"} hint="0-100" />
                <Stat label="Peak impact" value={d.peak_metrics?.impact_score.toFixed(2) ?? "—"} />
                <Stat label="Failed" value={<span style={{ color: STATUS.FAILED.color }}>{counts.FAILED}</span>} />
                <Stat label="On backup" value={<span style={{ color: STATUS.ON_BACKUP.color }}>{counts.ON_BACKUP}</span>} />
                <Stat label="Degraded" value={<span style={{ color: STATUS.DEGRADED.color }}>{counts.DEGRADED}</span>} />
                <Stat label="People affected" value={formatNumber(currentPoint?.affected_population ?? 0)} />
              </div>

              {/* ---------------------------------------------------------------- playback */}
              <div className="flex flex-wrap items-center gap-2 bg-panel px-3 py-2" data-testid="playback">
                <button type="button" aria-label="Previous step" onClick={() => { setPlaying(false); setFrameIndex(Math.max(0, frameIndex - 1)); }} className="rounded-sm p-1 hover:bg-raised">
                  <ChevronLeft className="size-4" />
                </button>
                <button
                  type="button"
                  aria-label={playing ? "Pause" : "Play cascade"}
                  onClick={() => {
                    if (!playing && frameIndex >= lastFrame) setFrameIndex(0);
                    setPlaying((p) => !p);
                  }}
                  className="rounded-sm bg-raised p-1 hover:bg-line-strong"
                >
                  {playing ? <Pause className="size-4" /> : <Play className="size-4" />}
                </button>
                <button type="button" aria-label="Next step" onClick={() => { setPlaying(false); setFrameIndex(Math.min(lastFrame, frameIndex + 1)); }} className="rounded-sm p-1 hover:bg-raised">
                  <ChevronRight className="size-4" />
                </button>
                <input
                  type="range"
                  min={0}
                  max={frames.length - 1}
                  value={frameIndex}
                  onChange={(e) => { setPlaying(false); setFrameIndex(Number(e.target.value)); }}
                  aria-label="Cascade step"
                  className="min-w-40 flex-1 accent-[#58a6ff]"
                />
                <span className="w-56 text-right font-mono text-[11px] text-muted" aria-live="polite">
                  {frameIndex === 0
                    ? "before any change"
                    : `${formatMinutes(frame.t)} · wave ${frame.wave} · ${frame.changes.length} change${frame.changes.length === 1 ? "" : "s"}`}
                  {" "}({frameIndex}/{frames.length - 1})
                </span>
              </div>

              {/* ---------------------------------------------------------------- views */}
              <div className="grid min-h-[380px] gap-px bg-line xl:grid-cols-[minmax(0,1fr)_260px]">
                <Panel
                  title={<span className="flex items-center gap-2">District at this moment</span>}
                  className="min-h-[380px] border-0"
                  actions={<Segmented<View> label="View" value={view} onChange={setView} options={[{ value: "map", label: "Map" }, { value: "graph", label: "Graph" }]} />}
                >
                  {graph.isPending || basemap.isPending ? (
                    <Loading />
                  ) : graph.isError || basemap.isError || !bounds ? (
                    <ErrorState error={graph.error ?? basemap.error ?? new Error("No district boundary")} />
                  ) : view === "map" ? (
                    <TwinMap graph={graph.data} basemap={basemap.data as unknown as FeatureCollection} bounds={bounds} highlight={highlight} showAccess={false} onSelect={select} statuses={statuses} />
                  ) : (
                    <DependencyGraph graph={graph.data} highlight={highlight} showAccess={false} onSelect={select} statuses={statuses} />
                  )}
                </Panel>
                <Panel title="Asset at this moment" className="border-0">
                  {selected ? (
                    <AssetAtTime
                      code={selected}
                      status={statuses?.get(selected)}
                      change={changes.get(selected)}
                      finalState={d.final_state.find((s) => s.code === selected)}
                      onClose={() => setSelected(null)}
                    />
                  ) : (
                    <div className="flex flex-col gap-2 p-3 text-[12px] text-muted">
                      <p>Select an asset to see why it is in its current state.</p>
                      <ul className="flex flex-col gap-1">
                        {Object.entries(STATUS).map(([k, s]) => (
                          <li key={k} className="flex items-center gap-1.5">
                            <span className="size-2 rounded-full" style={{ background: s.color }} /> {s.label}
                          </li>
                        ))}
                      </ul>
                      <p className="text-[11px] text-dim">Fill = functional status · ring = physical condition.</p>
                    </div>
                  )}
                </Panel>
              </div>

              {/* ---------------------------------------------------------------- chart + log */}
              <div className="grid gap-px bg-line xl:grid-cols-2">
                <Panel className="h-64 border-0">
                  <ImpactChart timeline={d.timeline} horizon={d.horizon_minutes} currentT={frame.t} />
                </Panel>
                <Panel title={`Event timeline (${events.data?.length ?? 0})`} className="h-64 border-0">
                  <EventLog
                    events={events.data ?? []}
                    frame={frame}
                    onSelectAsset={(c) => setSelected(c)}
                    onSelectFrameAt={(t, wave) => {
                      const i = frames.findIndex((f) => f.t === t && f.wave === wave);
                      if (i >= 0) { setPlaying(false); setFrameIndex(i); }
                    }}
                  />
                </Panel>
              </div>

              {/* ---------------------------------------------------------------- services + reproducibility */}
              <div className="grid gap-px bg-line md:grid-cols-2">
                <Panel title="Critical services at the horizon" className="border-0" bodyClassName="p-3">
                  <ul className="flex flex-col gap-1.5">
                    {d.final_metrics?.service_availability.map((s) => (
                      <li key={s.service} className="grid grid-cols-[110px_1fr_48px] items-center gap-2 text-[12px]">
                        <span className="capitalize text-muted">{s.service.replace("_", " ")}</span>
                        <span className="h-1.5 rounded-full bg-raised" role="meter" aria-valuenow={Math.round(s.availability * 100)} aria-valuemin={0} aria-valuemax={100} aria-label={`${s.service} availability`}>
                          <span className="block h-1.5 rounded-full bg-fg/70" style={{ width: `${s.availability * 100}%` }} />
                        </span>
                        <span className="text-right font-mono tabular-nums">{Math.round(s.availability * 100)}%</span>
                      </li>
                    ))}
                  </ul>
                  {d.final_metrics && d.final_metrics.isolated_assets.length > 0 && (
                    <p className="mt-2 flex items-center gap-1 text-[11px] text-warn">
                      <ShieldAlert className="size-3.5" /> Isolated (no path to a source): {d.final_metrics.isolated_assets.join(", ")}
                    </p>
                  )}
                </Panel>
                <Panel title="Reproducibility" className="border-0" bodyClassName="flex flex-col gap-2 p-3 text-[12px]">
                  <div className="font-mono text-[11px] text-muted break-all">result {d.result_hash}</div>
                  <div className="text-[11px] text-dim">
                    engine {d.engine_version} · scoring {d.scoring_version} · dataset {d.dataset_version} · {d.duration_ms?.toFixed(0)} ms
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <button type="button" onClick={() => replay.mutate(d.id)} disabled={replay.isPending} className="rounded-sm border border-line-strong px-2 py-0.5 hover:bg-raised">
                      {replay.isPending ? "Replaying…" : "Replay & verify"}
                    </button>
                    {replay.data && (
                      <span className={cn("flex items-center gap-1", replay.data.hash_matches ? "text-ok" : "text-crit")} data-testid="replay-result">
                        {replay.data.hash_matches ? <CheckCircle2 className="size-3.5" /> : <XCircle className="size-3.5" />}
                        {replay.data.hash_matches ? "Identical result" : "Result differs"}
                        {!replay.data.snapshot_matches && " (twin changed since this run)"}
                      </span>
                    )}
                    <button type="button" onClick={() => apply.mutate(d.id)} disabled={apply.isPending} className="rounded-sm border border-line-strong px-2 py-0.5 hover:bg-raised">
                      {apply.isSuccess ? "Applied to operational picture" : "Apply to operational picture"}
                    </button>
                  </div>
                  {(replay.isError || apply.isError) && <ErrorState error={replay.error ?? apply.error} />}
                </Panel>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
