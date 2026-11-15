"use client";

import Link from "next/link";

import { ErrorState, Loading, Panel, Stat } from "@/components/ui/primitives";
import { CATEGORY, CONDITION, formatNumber } from "@/lib/domain";
import { useInfrastructureHealth, useSystemStatus } from "@/lib/queries";

const CAPABILITY_LABELS: Record<string, string> = {
  digital_twin: "Infrastructure digital twin",
  simulation: "Cascading-failure simulation",
  agents: "Multi-agent analysis",
  recovery: "Recovery strategy engine",
  governance: "Approval & governance",
};

/**
 * Phase 1 Command Center: baseline health of the district from the real backend, plus an
 * honest capability list. Incident, simulation and recovery panels arrive with their phases.
 */
export function CommandCenterOverview() {
  const health = useInfrastructureHealth();
  const status = useSystemStatus();

  return (
    <div className="grid gap-3 p-3 lg:grid-cols-3">
      <Panel title="District baseline" className="lg:col-span-2" bodyClassName="p-3">
        {health.isPending ? (
          <Loading />
        ) : health.isError ? (
          <ErrorState error={health.error} onRetry={() => health.refetch()} />
        ) : (
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat label="Infrastructure assets" value={health.data.infrastructure_asset_count} />
              <Stat label="Dependencies" value={health.data.dependency_count} />
              <Stat label="Demand zones" value={health.data.demand_zone_count} />
              <Stat label="Population (synthetic)" value={formatNumber(health.data.population_total)} />
            </div>
            <div className="flex flex-wrap gap-3 text-[12px]">
              {Object.entries(health.data.by_condition).map(([condition, count]) => (
                <span key={condition} className="flex items-center gap-1.5">
                  <span
                    className="size-2 rounded-full"
                    style={{ background: CONDITION[condition as keyof typeof CONDITION].color }}
                  />
                  {count} {CONDITION[condition as keyof typeof CONDITION].label.toLowerCase()}
                </span>
              ))}
              <span className="text-dim">
                · picture: {health.data.picture} · {health.data.component_count} independent
                systems
              </span>
            </div>
            <table className="w-full text-left text-[12px]">
              <thead className="text-[10px] uppercase tracking-[0.08em] text-dim">
                <tr>
                  <th className="py-1 font-medium">Category</th>
                  <th className="py-1 text-right font-medium">Assets</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(health.data.by_category).map(([category, c]) => (
                  <tr key={category} className="border-t border-line">
                    <td className="py-1">{CATEGORY[category as keyof typeof CATEGORY].label}</td>
                    <td className="py-1 text-right font-mono tabular-nums">{c.total}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Link href="/twin" className="self-start text-focus hover:underline">
              Open the Infrastructure Twin →
            </Link>
          </div>
        )}
      </Panel>
      <Panel title="Platform capabilities" bodyClassName="p-3">
        {status.isPending ? (
          <Loading />
        ) : status.isError ? (
          <ErrorState error={status.error} onRetry={() => status.refetch()} />
        ) : (
          <ul className="flex flex-col gap-2">
            {Object.entries(CAPABILITY_LABELS).map(([key, label]) => {
              const on = status.data.capabilities[key as keyof typeof status.data.capabilities];
              return (
                <li key={key} className="flex items-center justify-between gap-2">
                  <span className={on ? "" : "text-dim"}>{label}</span>
                  <span className={on ? "text-ok" : "text-dim"}>{on ? "available" : "planned"}</span>
                </li>
              );
            })}
            <li className="mt-2 border-t border-line pt-2 text-[11px] text-dim">
              Build phase {status.data.capabilities.phase} · API v{status.data.app_version} · DB
              rev {status.data.database_revision ?? "—"}
            </li>
          </ul>
        )}
      </Panel>
    </div>
  );
}
