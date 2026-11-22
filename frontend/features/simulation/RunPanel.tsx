"use client";

import { Play, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { ErrorState, IconButton, SectionLabel, Segmented, cn } from "@/components/ui/primitives";
import type { Schemas } from "@/lib/api";
import { formatMinutes } from "@/lib/domain";
import { type SimulationRequest, useGraph, useRunSimulation, useScenarios } from "@/lib/queries";
import { hasRole, useSession } from "@/lib/session";

type Mode = "scenario" | "custom";
type Condition = "DAMAGED" | "DEGRADED" | "DESTROYED";
interface FailureRow {
  asset_code: string;
  condition: Condition;
  t_minutes: number;
}

const HORIZONS = [
  { value: 360, label: "6 h" },
  { value: 1440, label: "24 h" },
  { value: 4320, label: "72 h" },
];

function describeEvent(e: Schemas["ScenarioOut"]["initiating_events"][number]): string {
  if (e.kind === "AREA_FLOOD") return `${formatMinutes(e.t_minutes ?? 0)} flood to ${e.water_level_m} m`;
  if (e.kind === "ASSET_FAILURE") return `${formatMinutes(e.t_minutes ?? 0)} ${e.asset_code} ${(e.condition ?? "DAMAGED").toLowerCase()}`;
  if (e.kind === "BACKUP_SUPPLIED") return `${formatMinutes(e.t_minutes ?? 0)} ${e.asset_code} +${e.minutes} min backup`;
  return `${formatMinutes(e.t_minutes ?? 0)} ${e.asset_code} restored`;
}

export function RunPanel({ onRun }: { onRun: (id: string) => void }) {
  const scenarios = useScenarios();
  const graph = useGraph();
  const run = useRunSimulation();
  const [mode, setMode] = useState<Mode>("scenario");
  const [scenarioKey, setScenarioKey] = useState<string | null>(null);
  const [rows, setRows] = useState<FailureRow[]>([{ asset_code: "SUB-02", condition: "DAMAGED", t_minutes: 0 }]);
  const [horizon, setHorizon] = useState(4320);
  const [label, setLabel] = useState("");
  const [apply, setApply] = useState(false);
  const canApply = hasRole(useSession(), "operator");

  const assets = useMemo(
    () => (graph.data?.nodes ?? []).filter((n) => n.category !== "DEMAND_ZONE"),
    [graph.data],
  );
  const selectedScenario = scenarios.data?.find((s) => s.key === scenarioKey) ?? null;
  const canRun = mode === "scenario" ? scenarioKey !== null : rows.length > 0;

  const submit = () => {
    const base = {
      horizon_minutes: horizon,
      label: label.trim() || null,
      apply_to_picture: apply && canApply,
    };
    const body: SimulationRequest =
      mode === "scenario"
        ? { ...base, scenario_key: scenarioKey }
        : {
            ...base,
            initiating_events: rows.map((r) => ({ kind: "ASSET_FAILURE" as const, ...r })),
          };
    run.mutate(body, { onSuccess: (detail) => onRun(detail.id) });
  };

  return (
    <div className="flex flex-col gap-3 p-3" data-testid="run-panel">
      <Segmented<Mode>
        label="Initiating events"
        value={mode}
        onChange={setMode}
        options={[
          { value: "scenario", label: "Scenario" },
          { value: "custom", label: "Custom failures" },
        ]}
      />

      {mode === "scenario" ? (
        <fieldset className="flex flex-col gap-1.5">
          <legend className="sr-only">Scenario</legend>
          {scenarios.isError && <ErrorState error={scenarios.error} />}
          {scenarios.data?.map((s) => (
            <label
              key={s.key}
              className={cn(
                "cursor-pointer rounded-sm border border-line p-2 hover:bg-raised",
                scenarioKey === s.key && "border-focus bg-raised",
              )}
            >
              <span className="flex items-center gap-2">
                <input
                  type="radio"
                  name="scenario"
                  checked={scenarioKey === s.key}
                  onChange={() => {
                    setScenarioKey(s.key);
                    setHorizon(s.horizon_minutes);
                  }}
                  className="accent-[#5ab9fc]"
                />
                <span className="font-medium">{s.name}</span>
              </span>
              <span className="mt-1 block text-[13px] text-muted">{s.description}</span>
            </label>
          ))}
          {selectedScenario && (
            <ul className="text-[13px] text-dim">
              {selectedScenario.initiating_events.map((e, i) => (
                <li key={i} className="font-mono">{describeEvent(e)}</li>
              ))}
            </ul>
          )}
        </fieldset>
      ) : (
        <div className="flex flex-col gap-1.5">
          {rows.map((r, i) => (
            <div key={i} className="grid grid-cols-[1fr_auto_52px_auto] items-center gap-1">
              <select
                aria-label={`Failed asset ${i + 1}`}
                value={r.asset_code}
                onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, asset_code: e.target.value } : x)))}
                className="field min-w-0"
              >
                {assets.map((a) => (
                  <option key={a.code} value={a.code}>
                    {a.code} · {a.name}
                  </option>
                ))}
              </select>
              <select
                aria-label={`Condition ${i + 1}`}
                value={r.condition}
                onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, condition: e.target.value as Condition } : x)))}
                className="field"
              >
                <option value="DAMAGED">damaged</option>
                <option value="DEGRADED">degraded</option>
                <option value="DESTROYED">destroyed</option>
              </select>
              <input
                type="number"
                min={0}
                aria-label={`Minutes after start ${i + 1}`}
                value={r.t_minutes}
                onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, t_minutes: Math.max(0, Number(e.target.value)) } : x)))}
                className="field text-right font-mono"
              />
              <IconButton aria-label={`Remove failure ${i + 1}`} onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                <Trash2 className="size-3.5" />
              </IconButton>
            </div>
          ))}
          <button
            type="button"
            onClick={() => setRows([...rows, { asset_code: assets[0]?.code ?? "SUB-01", condition: "DAMAGED", t_minutes: 0 }])}
            className="flex items-center gap-1 self-start text-[14px] text-focus hover:underline"
          >
            <Plus className="size-3.5" /> Add failure
          </button>
          <p className="text-[13px] text-dim">Times are minutes after the start of the simulation.</p>
        </div>
      )}

      <div>
        <SectionLabel>Horizon</SectionLabel>
        <Segmented<string>
          label="Horizon"
          value={String(horizon)}
          onChange={(v) => setHorizon(Number(v))}
          options={HORIZONS.map((h) => ({ value: String(h.value), label: h.label }))}
        />
      </div>

      <label className="block">
        <SectionLabel>Label (optional)</SectionLabel>
        <input
          value={label}
          maxLength={120}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="e.g. Riverside drill #1"
          className="field placeholder:text-dim"
        />
      </label>

      <label
        className="flex cursor-pointer items-center gap-2 text-[14px] text-muted"
        title={canApply ? undefined : "Applying to the operational picture needs the operator role"}
      >
        <input
          type="checkbox"
          checked={apply && canApply}
          disabled={!canApply}
          onChange={(e) => setApply(e.target.checked)}
          className="accent-[#5ab9fc]"
        />
        Apply result to the operational picture
      </label>

      <button
        type="button"
        disabled={!canRun || run.isPending}
        onClick={submit}
        className="btn btn-primary"
      >
        <Play className="size-3.5" aria-hidden />
        {run.isPending ? "Simulating…" : "Run simulation"}
      </button>
      {run.isError && <ErrorState error={run.error} />}
    </div>
  );
}
