"use client";

import { Send } from "lucide-react";
import { useMemo, useState } from "react";

import { ErrorState, SectionLabel, Segmented } from "@/components/ui/primitives";
import { useAnalyze, useCreateIncident, useGraph } from "@/lib/queries";

type Mode = "report" | "structured";

/** Example wording only: the operator edits or replaces it; nothing is submitted automatically. */
const EXAMPLES = [
  "Explosion reported at the Riverside substation around 06:40. East bank lights out, Riverside Community Hospital running on generator.",
  "Northgate Substation tripped on a protection fault. Thirty minutes later the central telephone exchange failed; no signal across the district.",
  "Something happened downtown, lots of sirens and people gathering.",
];

export function IncidentIntake({ onStarted }: { onStarted: (incidentId: string, runId: string) => void }) {
  const create = useCreateIncident();
  const analyze = useAnalyze();
  const graph = useGraph();
  const [mode, setMode] = useState<Mode>("report");
  const [report, setReport] = useState("");
  const [asset, setAsset] = useState("SUB-02");
  const [title, setTitle] = useState("");
  const assets = useMemo(() => (graph.data?.nodes ?? []).filter((n) => n.category !== "DEMAND_ZONE"), [graph.data]);
  const busy = create.isPending || analyze.isPending;

  const submit = async () => {
    const incident = await create.mutateAsync(
      mode === "report"
        ? { source: "FREE_TEXT", raw_report: report }
        : {
            source: "STRUCTURED",
            title: title.trim() || `${asset} failure`,
            incident_type: "EQUIPMENT_FAILURE",
            severity: "HIGH",
            initiating_events: [{ kind: "ASSET_FAILURE", asset_code: asset, condition: "DAMAGED", t_minutes: 0 }],
          },
    );
    const run = await analyze.mutateAsync(incident.id);
    onStarted(incident.id, run.workflow_run_id);
    setReport("");
  };

  return (
    <div className="flex flex-col gap-3 p-3" data-testid="incident-intake">
      <Segmented<Mode>
        label="Incident input"
        value={mode}
        onChange={setMode}
        options={[
          { value: "report", label: "Free-text report" },
          { value: "structured", label: "Structured" },
        ]}
      />
      {mode === "report" ? (
        <>
          <label className="block">
            <SectionLabel>Report (treated as untrusted text)</SectionLabel>
            <textarea
              value={report}
              onChange={(e) => setReport(e.target.value)}
              rows={5}
              maxLength={10000}
              placeholder="Describe what happened, where, and what is affected…"
              className="w-full resize-y rounded-sm border border-line-strong bg-bg p-2 text-[12px] placeholder:text-dim"
            />
          </label>
          <div className="flex flex-col gap-1">
            <SectionLabel>Example wording</SectionLabel>
            {EXAMPLES.map((ex) => (
              <button key={ex} type="button" onClick={() => setReport(ex)} className="truncate text-left text-[11px] text-focus hover:underline" title={ex}>
                {ex}
              </button>
            ))}
          </div>
        </>
      ) : (
        <>
          <label className="block">
            <SectionLabel>Damaged asset</SectionLabel>
            <select value={asset} onChange={(e) => setAsset(e.target.value)} className="w-full rounded-sm border border-line-strong bg-bg px-1 py-1 text-[12px]">
              {assets.map((a) => (
                <option key={a.code} value={a.code}>
                  {a.code} · {a.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <SectionLabel>Title</SectionLabel>
            <input value={title} maxLength={160} onChange={(e) => setTitle(e.target.value)} placeholder={`${asset} failure`} className="w-full rounded-sm border border-line-strong bg-bg px-2 py-1 text-[12px] placeholder:text-dim" />
          </label>
        </>
      )}
      <button
        type="button"
        disabled={busy || (mode === "report" && report.trim().length < 10)}
        onClick={() => void submit().catch(() => undefined)}
        className="flex items-center justify-center gap-1.5 rounded-sm bg-focus px-3 py-1.5 font-medium text-bg disabled:opacity-40"
      >
        <Send className="size-3.5" aria-hidden />
        {busy ? "Submitting…" : "Report & analyse"}
      </button>
      {(create.isError || analyze.isError) && <ErrorState error={create.error ?? analyze.error} />}
    </div>
  );
}
