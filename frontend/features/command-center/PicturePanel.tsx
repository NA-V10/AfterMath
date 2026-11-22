"use client";

import { AlertTriangle, RotateCcw } from "lucide-react";
import Link from "next/link";

import { ErrorState, Loading, Panel, Stat } from "@/components/ui/primitives";
import { STATUS, formatMinutes, formatNumber } from "@/lib/domain";
import { usePicture, useResetPicture } from "@/lib/queries";
import { hasRole, useSession } from "@/lib/session";

/** The current operational picture: the baseline, or a simulation applied to it. */
export function PicturePanel() {
  const picture = usePicture();
  const reset = useResetPicture();
  const canReset = hasRole(useSession(), "admin");

  return (
    <Panel
      title="Operational picture"
      className="lg:col-span-3"
      bodyClassName="p-4"
      actions={
        picture.data?.source === "simulation" && (
          <button
            type="button"
            onClick={() => reset.mutate("Reset from Command Center")}
            disabled={reset.isPending || !canReset}
            title={canReset ? undefined : "Resetting the operational picture needs the admin role"}
            className="btn btn-secondary btn-sm"
          >
            <RotateCcw aria-hidden /> Reset to baseline
          </button>
        )
      }
    >
      {picture.isPending ? (
        <Loading />
      ) : picture.isError ? (
        <ErrorState error={picture.error} onRetry={() => picture.refetch()} />
      ) : (
        <div className="flex flex-col gap-3" data-testid="operational-picture">
          <div className="flex flex-wrap items-center gap-2 text-[14px]">
            {picture.data.source === "baseline" ? (
              <span className="text-muted">
                Baseline: no incident applied. Run a simulation in the{" "}
                <Link href="/lab" className="link">Simulation Lab</Link> and apply it to
                see its consequences here.
              </span>
            ) : (
              <span>
                Showing simulation <span className="font-medium">{picture.data.label ?? picture.data.simulation_id?.slice(0, 8)}</span>{" "}
                <span className="text-muted">as of {formatMinutes(picture.data.as_of_minutes)}</span>
              </span>
            )}
            {picture.data.stale && (
              <span className="flex items-center gap-1 text-warn">
                <AlertTriangle className="size-3.5" /> The twin changed after this picture was applied.
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-6">
            <Stat label="Impact score" value={picture.data.metrics.impact_score.toFixed(2)} />
            {(["FAILED", "ON_BACKUP", "DEGRADED", "OPERATIONAL"] as const).map((s) => (
              <Stat
                key={s}
                label={STATUS[s].label}
                value={(() => {
                  const n = picture.data.metrics.status_counts[s] ?? 0;
                  // Only colour non-zero problem counts: a red "0" reads as an alarm.
                  const color = s !== "OPERATIONAL" && n > 0 ? STATUS[s].color : undefined;
                  return <span style={{ color }}>{n}</span>;
                })()}
              />
            ))}
            <Stat label="People affected" value={formatNumber(picture.data.metrics.affected_population)} />
          </div>
          <ul className="grid gap-x-6 gap-y-1 sm:grid-cols-2 lg:grid-cols-4">
            {picture.data.metrics.service_availability.map((s) => (
              <li key={s.service} className="grid grid-cols-[120px_1fr_44px] items-center gap-2 text-[14px]">
                <span className="capitalize text-muted">{s.service.replace("_", " ")}</span>
                <span className="h-1.5 rounded-full bg-raised">
                  <span className="block h-1.5 rounded-full bg-fg/70" style={{ width: `${s.availability * 100}%` }} />
                </span>
                <span className="text-right font-mono tabular-nums">{Math.round(s.availability * 100)}%</span>
              </li>
            ))}
          </ul>
          {reset.isError && <ErrorState error={reset.error} />}
        </div>
      )}
    </Panel>
  );
}
