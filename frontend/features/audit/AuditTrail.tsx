"use client";

import { useState } from "react";

import { ErrorState, Loading, PageHeader, Panel } from "@/components/ui/primitives";
import { useAuditLog, useVerifyChain } from "@/lib/queries";

import { ReportsPanel } from "./ReportsPanel";

/** Read-only view of the append-only, hash-chained audit log. */
export function AuditTrail() {
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const cursor = cursors[cursors.length - 1];
  const audit = useAuditLog(cursor);
  const verify = useVerifyChain();

  return (
    <div className="flex min-h-full flex-col">
      <PageHeader
        title="Audit & Reports"
        hint="Every change is recorded in an append-only, hash-chained log. Reports are built from stored records."
      />
      <div className="grid gap-4 p-5 min-[1680px]:grid-cols-[minmax(0,1fr)_400px]">
      <Panel
        title="Audit trail"
        actions={
          <span className="flex items-center gap-3 text-[13px] text-muted">
            Newest first
            <button
              type="button"
              onClick={() => verify.mutate()}
              disabled={verify.isPending}
              className="btn btn-secondary btn-sm"
            >
              {verify.isPending ? "Verifying…" : "Verify chain"}
            </button>
            {verify.data && (
              <span data-testid="chain-result" className={verify.data.ok ? "text-ok" : "font-medium text-crit"}>
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
            <table className="w-full min-w-[720px] text-left text-[14px]">
              <thead className="text-[13px] text-muted">
                <tr className="border-b border-line">
                  <th className="px-4 py-2 font-medium">#</th>
                  <th className="px-4 py-2 font-medium">Time (UTC)</th>
                  <th className="px-4 py-2 font-medium">Actor</th>
                  <th className="px-4 py-2 font-medium">Action</th>
                  <th className="px-4 py-2 font-medium">Entity</th>
                  <th className="px-4 py-2 font-medium">Hash</th>
                </tr>
              </thead>
              <tbody>
                {audit.data.items.map((r) => (
                  <tr key={r.id} className="border-b border-line align-top hover:bg-panel-2">
                    <td className="px-4 py-2 font-mono text-muted">{r.id}</td>
                    <td className="px-4 py-2 font-mono whitespace-nowrap">
                      {r.occurred_at.replace("T", " ").slice(0, 19)}
                    </td>
                    <td className="px-4 py-2">
                      {r.actor_id.includes(":") ? (
                        r.actor_id
                      ) : (
                        <>
                          <span className="text-muted">{r.actor_type.toLowerCase()}:</span>
                          {r.actor_id}
                        </>
                      )}
                    </td>
                    <td className="px-4 py-2 font-mono">{r.action}</td>
                    <td className="px-4 py-2">
                      {r.entity_type}
                      {r.entity_id && (
                        <span className="font-mono text-muted" title={r.entity_id}>
                          {" "}
                          · {/^[0-9a-f-]{36}$/.test(r.entity_id) ? `${r.entity_id.slice(0, 8)}…` : r.entity_id}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2 font-mono text-muted" title={r.hash}>
                      {r.hash.slice(0, 12)}…
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="flex justify-end gap-2 border-t border-line px-4 py-2">
          <button
            type="button"
            disabled={cursors.length === 1}
            onClick={() => setCursors((c) => c.slice(0, -1))}
            className="btn btn-secondary btn-sm"
          >
            Newer
          </button>
          <button
            type="button"
            disabled={!audit.data?.next_cursor}
            onClick={() => audit.data?.next_cursor && setCursors((c) => [...c, audit.data.next_cursor])}
            className="btn btn-secondary btn-sm"
          >
            Older
          </button>
        </div>
      </Panel>
      <ReportsPanel />
      </div>
    </div>
  );
}
