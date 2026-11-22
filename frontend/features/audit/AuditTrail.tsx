"use client";

import { useState } from "react";

import { ErrorState, Loading, Panel } from "@/components/ui/primitives";
import { useAuditLog, useVerifyChain } from "@/lib/queries";

/** Read-only view of the append-only, hash-chained audit log. */
export function AuditTrail() {
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const cursor = cursors[cursors.length - 1];
  const audit = useAuditLog(cursor);
  const verify = useVerifyChain();

  return (
    <div className="p-3">
      <Panel
        title="Audit trail"
        actions={
          <span className="flex items-center gap-2 text-[11px] text-dim">
            append-only · hash-chained · newest first
            <button
              type="button"
              onClick={() => verify.mutate()}
              disabled={verify.isPending}
              className="rounded-sm border border-line-strong px-1.5 py-0.5 text-fg hover:bg-raised disabled:opacity-40"
            >
              {verify.isPending ? "Verifying…" : "Verify chain"}
            </button>
            {verify.data && (
              <span data-testid="chain-result" className={verify.data.ok ? "text-ok" : "font-semibold text-crit"}>
                {verify.data.ok
                  ? `intact · ${verify.data.records_checked} records`
                  : `BROKEN at record #${verify.data.first_broken_id}`}
              </span>
            )}
          </span>
        }
      >
        {audit.isPending ? (
          <Loading />
        ) : audit.isError ? (
          <ErrorState error={audit.error} onRetry={() => audit.refetch()} />
        ) : audit.data.items.length === 0 ? (
          <div className="p-6 text-center text-muted">No audit records yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-[12px]">
              <thead className="text-[10px] uppercase tracking-[0.08em] text-dim">
                <tr className="border-b border-line">
                  <th className="px-3 py-1.5 font-medium">#</th>
                  <th className="px-3 py-1.5 font-medium">Time (UTC)</th>
                  <th className="px-3 py-1.5 font-medium">Actor</th>
                  <th className="px-3 py-1.5 font-medium">Action</th>
                  <th className="px-3 py-1.5 font-medium">Entity</th>
                  <th className="px-3 py-1.5 font-medium">Hash</th>
                </tr>
              </thead>
              <tbody>
                {audit.data.items.map((r) => (
                  <tr key={r.id} className="border-b border-line align-top hover:bg-panel-2">
                    <td className="px-3 py-1.5 font-mono text-dim">{r.id}</td>
                    <td className="px-3 py-1.5 font-mono whitespace-nowrap">
                      {r.occurred_at.replace("T", " ").slice(0, 19)}
                    </td>
                    <td className="px-3 py-1.5">
                      <span className="text-dim">{r.actor_type.toLowerCase()}:</span> {r.actor_id}
                    </td>
                    <td className="px-3 py-1.5 font-mono">{r.action}</td>
                    <td className="px-3 py-1.5">
                      {r.entity_type}
                      {r.entity_id && <span className="text-muted"> · {r.entity_id}</span>}
                    </td>
                    <td className="px-3 py-1.5 font-mono text-dim" title={r.hash}>
                      {r.hash.slice(0, 12)}…
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="flex justify-end gap-2 border-t border-line px-3 py-1.5">
          <button
            type="button"
            disabled={cursors.length === 1}
            onClick={() => setCursors((c) => c.slice(0, -1))}
            className="rounded-sm border border-line-strong px-2 py-0.5 disabled:opacity-40"
          >
            Newer
          </button>
          <button
            type="button"
            disabled={!audit.data?.next_cursor}
            onClick={() => audit.data?.next_cursor && setCursors((c) => [...c, audit.data.next_cursor])}
            className="rounded-sm border border-line-strong px-2 py-0.5 disabled:opacity-40"
          >
            Older
          </button>
        </div>
      </Panel>
    </div>
  );
}
