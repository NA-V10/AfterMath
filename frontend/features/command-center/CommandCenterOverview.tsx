"use client";

import { ArrowRight, CheckCircle2, Clock, Gavel } from "lucide-react";
import Link from "next/link";

import { ErrorState, Loading, PageHeader, Panel, Stat } from "@/components/ui/primitives";
import { CATEGORY, CONDITION, formatNumber } from "@/lib/domain";
import { useIncidents, useInfrastructureHealth, useSystemStatus } from "@/lib/queries";

import { PicturePanel } from "./PicturePanel";

const ACTIVE = new Set(["REPORTED", "ANALYZING", "ANALYZED", "AWAITING_APPROVAL", "RECOVERING"]);

function since(iso: string): string {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000));
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} days ago`;
}

/** What needs a person now: incidents with validated plans waiting for an approver. */
function DecisionQueue() {
  const incidents = useIncidents();
  if (incidents.isPending) return <Loading label="Loading incidents" />;
  if (incidents.isError) return <ErrorState error={incidents.error} onRetry={() => incidents.refetch()} />;
  const items = incidents.data.items;
  const waiting = items.filter((i) => i.status === "AWAITING_APPROVAL");
  const active = items.filter((i) => ACTIVE.has(i.status));
  const recovered = items.filter((i) => i.status === "RECOVERED");
  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="grid grid-cols-3 gap-3">
        <Stat label="Waiting for a decision" value={waiting.length} />
        <Stat label="Open incidents" value={active.length} />
        <Stat label="Recovered" value={recovered.length} />
      </div>
      {waiting.length === 0 ? (
        <p className="flex items-center gap-2 text-muted">
          <CheckCircle2 className="size-4 text-ok" aria-hidden /> No plan is waiting for approval.
        </p>
      ) : (
        <ul className="flex flex-col gap-2" aria-label="Incidents waiting for a decision" data-testid="decision-queue">
          {waiting.slice(0, 6).map((i) => (
            <li key={i.id}>
              <Link
                href={`/recovery#incident=${i.id}`}
                className="card-link flex items-center gap-3 rounded-lg border border-line-strong bg-panel-2 px-3.5 py-3"
              >
                <Gavel className="size-4 shrink-0 text-focus" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline gap-2">
                    <span className="font-mono text-[14px]">{i.reference}</span>
                    <span className="text-[13px] text-muted">{since(i.created_at)}</span>
                  </span>
                  <span className="block truncate text-[14px] text-muted">{i.title ?? i.raw_report}</span>
                </span>
                <ArrowRight className="size-4 shrink-0 text-muted" aria-hidden />
              </Link>
            </li>
          ))}
          {waiting.length > 6 && (
            <li className="text-[13px] text-muted">
              and {waiting.length - 6} more in{" "}
              <Link href="/recovery" className="link">
                Recovery Command
              </Link>
            </li>
          )}
        </ul>
      )}
      {active.some((i) => i.status === "ANALYZING") && (
        <p className="flex items-center gap-2 text-[13px] text-muted">
          <Clock className="size-3.5" aria-hidden /> Agents are analysing{" "}
          {active.filter((i) => i.status === "ANALYZING").length} incident(s):{" "}
          <Link href="/agents" className="link">
            follow them in Agent Activity
          </Link>
        </p>
      )}
    </div>
  );
}

/**
 * Command Center: what needs a decision, the current operational picture (baseline or an applied
 * simulation), the district's composition and the system's state.
 */
export function CommandCenterOverview() {
  const health = useInfrastructureHealth();
  const status = useSystemStatus();

  return (
    <div className="flex min-h-full flex-col">
      <PageHeader
        title="Command Center"
        hint="Decisions waiting, the current operational picture and the district at a glance."
      />
      <div className="grid gap-4 p-5 lg:grid-cols-3">
        <Panel title="Needs a decision" className="lg:col-span-2">
          <DecisionQueue />
        </Panel>
        <Panel title="System" bodyClassName="p-4">
          {status.isPending ? (
            <Loading />
          ) : status.isError ? (
            <ErrorState error={status.error} onRetry={() => status.refetch()} />
          ) : (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-[14px]">
              <dt className="text-muted">Language model</dt>
              <dd className="font-mono">{status.data.llm}</dd>
              <dt className="text-muted">Environment</dt>
              <dd>{status.data.environment}</dd>
              <dt className="text-muted">Dataset</dt>
              <dd className="font-mono">
                {status.data.dataset ? `${status.data.dataset.name} ${status.data.dataset.version}` : "not seeded"}
              </dd>
              <dt className="text-muted">API</dt>
              <dd className="font-mono">
                v{status.data.app_version} · db {status.data.database_revision ?? "—"}
              </dd>
            </dl>
          )}
        </Panel>
        <PicturePanel />
        <Panel title="District baseline" className="lg:col-span-3" bodyClassName="p-4">
          {health.isPending ? (
            <Loading />
          ) : health.isError ? (
            <ErrorState error={health.error} onRetry={() => health.refetch()} />
          ) : (
            <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <div className="flex flex-col gap-4">
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <Stat label="Assets" value={health.data.infrastructure_asset_count} />
                  <Stat label="Dependencies" value={health.data.dependency_count} />
                  <Stat label="Demand zones" value={health.data.demand_zone_count} />
                  <Stat label="Population (synthetic)" value={formatNumber(health.data.population_total)} />
                </div>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-[14px]">
                  {Object.entries(health.data.by_condition).map(([condition, count]) => (
                    <span key={condition} className="flex items-center gap-1.5">
                      <span
                        className="size-2 rounded-full"
                        style={{ background: CONDITION[condition as keyof typeof CONDITION].color }}
                      />
                      {count} {CONDITION[condition as keyof typeof CONDITION].label.toLowerCase()}
                    </span>
                  ))}
                  <span className="text-muted">
                    {health.data.component_count} independent systems · picture: {health.data.picture}
                  </span>
                </div>
                <Link href="/twin" className="link self-start">
                  Open the Infrastructure Twin
                </Link>
              </div>
              <table className="w-full text-left text-[14px]">
                <thead className="text-[13px] text-muted">
                  <tr>
                    <th className="py-1 font-medium">Category</th>
                    <th className="py-1 text-right font-medium">Assets</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(health.data.by_category).map(([category, c]) => (
                    <tr key={category} className="border-t border-line">
                      <td className="py-1.5">{CATEGORY[category as keyof typeof CATEGORY].label}</td>
                      <td className="py-1.5 text-right font-mono tabular-nums">{c.total}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
