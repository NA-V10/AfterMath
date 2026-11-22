"use client";

import { Download } from "lucide-react";
import { useState } from "react";

import { ErrorState, Loading, Panel } from "@/components/ui/primitives";
import { useIncidents } from "@/lib/queries";
import { downloadReport } from "@/lib/reports";

const REPORTABLE = new Set(["ANALYZED", "AWAITING_APPROVAL", "RECOVERING", "RECOVERED", "CLOSED"]);

/** One recovery report per analysed incident, built by the API from stored records only. */
export function ReportsPanel() {
  const incidents = useIncidents();
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const items = (incidents.data?.items ?? []).filter((i) => REPORTABLE.has(i.status));

  return (
    <Panel title="Recovery reports" bodyClassName="overflow-y-auto">
      {incidents.isPending ? (
        <Loading />
      ) : incidents.isError ? (
        <ErrorState error={incidents.error} onRetry={() => incidents.refetch()} />
      ) : items.length === 0 ? (
        <p className="p-4 text-muted">Reports appear once an incident has been analysed.</p>
      ) : (
        <ul aria-label="Recovery reports" data-testid="reports">
          {items.map((i) => (
            <li key={i.id} className="flex items-center gap-3 border-b border-line px-4 py-2.5">
              <span className="min-w-0 flex-1">
                <span className="flex items-baseline gap-2">
                  <span className="font-mono text-[14px]">{i.reference}</span>
                  <span className="text-[13px] text-muted">{i.status.replaceAll("_", " ").toLowerCase()}</span>
                </span>
                <span className="block truncate text-[13px] text-muted">{i.title ?? i.raw_report}</span>
              </span>
              <button
                type="button"
                disabled={busy === i.id}
                onClick={() => {
                  setBusy(i.id);
                  setError(null);
                  downloadReport(i)
                    .catch((e: Error) => setError(e))
                    .finally(() => setBusy(null));
                }}
                aria-label={`Download the ${i.reference} report`}
                className="btn btn-secondary btn-sm"
              >
                <Download aria-hidden /> Markdown
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <ErrorState error={error} />}
    </Panel>
  );
}
