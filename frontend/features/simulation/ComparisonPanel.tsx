"use client";

import { X } from "lucide-react";

import { ErrorState, IconButton, Loading, Panel, SectionLabel } from "@/components/ui/primitives";
import type { Schemas } from "@/lib/api";
import { STATUS, formatNumber } from "@/lib/domain";
import { useComparison } from "@/lib/queries";

function name(s: Schemas["SimulationSummary"]): string {
  return s.label ?? s.scenario_key ?? `custom ${s.id.slice(0, 8)}`;
}

function Codes({ codes }: { codes: string[] }) {
  return codes.length ? (
    <span className="font-mono text-[13px]">{codes.join(", ")}</span>
  ) : (
    <span className="text-dim">none</span>
  );
}

/** Server-side comparison of two runs (no comparison logic in the browser). */
export function ComparisonPanel({ a, b, onClose }: { a: string; b: string; onClose: () => void }) {
  const q = useComparison(a, b);
  return (
    <Panel
      title="Scenario comparison"
      className="h-full border-0"
      bodyClassName="overflow-auto p-3"
      actions={
        <IconButton aria-label="Close comparison" onClick={onClose}>
          <X className="size-3.5" />
        </IconButton>
      }
    >
      {q.isPending ? (
        <Loading />
      ) : q.isError ? (
        <ErrorState error={q.error} />
      ) : (
        <div className="flex flex-col gap-4" data-testid="comparison">
          <table className="w-full text-left text-[14px]">
            <thead className="text-[13px] text-dim">
              <tr>
                <th className="py-1 font-medium">Metric</th>
                <th className="py-1 text-right font-medium">A · {name(q.data.a)}</th>
                <th className="py-1 text-right font-medium">B · {name(q.data.b)}</th>
              </tr>
            </thead>
            <tbody className="font-mono tabular-nums">
              {(
                [
                  ["Final impact", q.data.a.impact_score?.toFixed(2), q.data.b.impact_score?.toFixed(2)],
                  ["Peak impact", q.data.a.peak_impact_score?.toFixed(2), q.data.b.peak_impact_score?.toFixed(2)],
                  ["Failed assets", q.data.a.failed_count, q.data.b.failed_count],
                  ["People affected", formatNumber(q.data.a.affected_population), formatNumber(q.data.b.affected_population)],
                ] as const
              ).map(([label, va, vb]) => (
                <tr key={label} className="border-t border-line">
                  <td className="py-1 font-sans text-muted">{label}</td>
                  <td className="py-1 text-right">{va ?? "—"}</td>
                  <td className="py-1 text-right">{vb ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-[14px]">
            Impact difference (B − A): <span className="font-mono">{q.data.impact_delta > 0 ? "+" : ""}{q.data.impact_delta.toFixed(2)}</span>
          </p>
          <div className="grid gap-2 text-[14px]">
            <div><SectionLabel>Failed only in A</SectionLabel><Codes codes={q.data.failed_only_in_a} /></div>
            <div><SectionLabel>Failed only in B</SectionLabel><Codes codes={q.data.failed_only_in_b} /></div>
            <div><SectionLabel>Failed in both</SectionLabel><Codes codes={q.data.failed_in_both} /></div>
          </div>
          <div>
            <SectionLabel>All status differences at the horizon ({q.data.status_differences.length})</SectionLabel>
            <ul className="grid grid-cols-1 gap-0.5 text-[13px] sm:grid-cols-2">
              {q.data.status_differences.map((d) => (
                <li key={d.code} className="flex items-center gap-1.5">
                  <span className="w-14 font-mono">{d.code}</span>
                  <span style={{ color: STATUS[d.a].color }}>{STATUS[d.a].label}</span>
                  <span className="text-dim">→</span>
                  <span style={{ color: STATUS[d.b].color }}>{STATUS[d.b].label}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </Panel>
  );
}
