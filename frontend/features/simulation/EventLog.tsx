"use client";

import { useEffect, useRef } from "react";

import { cn } from "@/components/ui/primitives";
import type { Schemas } from "@/lib/api";
import { STATUS, formatMinutes } from "@/lib/domain";

import type { Frame } from "./playback";

const KIND_LABEL: Record<Schemas["SimEvent"]["kind"], string> = {
  CONDITION_CHANGED: "condition",
  STATUS_CHANGED: "status",
  BACKUP_ENGAGED: "backup on",
  BACKUP_DISENGAGED: "backup off",
  BACKUP_EXHAUSTED: "backup empty",
  BACKUP_SUPPLIED: "power supplied",
  ISOLATION_DETECTED: "isolated",
  ISOLATION_RESOLVED: "reconnected",
  HORIZON_REACHED: "horizon",
};

function describe(e: Schemas["SimEvent"]): string {
  if (e.kind === "STATUS_CHANGED" && e.from_status && e.to_status) {
    return `${STATUS[e.from_status].label} → ${STATUS[e.to_status].label}`;
  }
  const d = e.details as Record<string, unknown>;
  if (e.kind === "CONDITION_CHANGED") {
    const cause = d.cause === "flood" ? ` (flood ${d.water_level_m} m > ${d.elevation_m} m)` : "";
    return `${String(d.from).toLowerCase()} → ${String(d.to).toLowerCase()}${cause}`;
  }
  if (e.kind === "BACKUP_ENGAGED") return `${d.remaining_minutes} min of backup left`;
  if (e.kind === "HORIZON_REACHED") return `${d.pending_events} pending event(s)`;
  return "";
}

export function EventLog({
  events,
  frame,
  onSelectAsset,
  onSelectFrameAt,
}: {
  events: Schemas["SimEvent"][];
  frame: Frame;
  onSelectAsset: (code: string) => void;
  onSelectFrameAt: (t: number, wave: number) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const row = container.current?.querySelector<HTMLElement>("[data-current='true']");
    row?.scrollIntoView({ block: "nearest" });
  }, [frame]);

  return (
    <div ref={container} className="h-full overflow-auto" data-testid="event-log">
      <table className="w-full text-left text-[13px]">
        <thead className="sticky top-0 bg-panel text-[13px] text-dim">
          <tr>
            <th className="px-2 py-1 font-medium">Time</th>
            <th className="px-2 py-1 font-medium">Wave</th>
            <th className="px-2 py-1 font-medium">Asset</th>
            <th className="px-2 py-1 font-medium">Event</th>
            <th className="px-2 py-1 font-medium">Detail</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => {
            const current = e.kind === "STATUS_CHANGED" && e.t_minutes === frame.t && e.wave === frame.wave;
            return (
              <tr
                key={e.seq}
                data-current={current}
                onClick={() => onSelectFrameAt(e.t_minutes, e.wave)}
                className={cn("cursor-pointer border-t border-line hover:bg-panel-2", current && "bg-raised")}
              >
                <td className="px-2 py-0.5 font-mono whitespace-nowrap">{formatMinutes(e.t_minutes)}</td>
                <td className="px-2 py-0.5 font-mono text-dim">{e.wave}</td>
                <td className="px-2 py-0.5 font-mono">
                  {e.asset_code && (
                    <button type="button" className="hover:underline" onClick={(ev) => { ev.stopPropagation(); onSelectAsset(e.asset_code!); }}>
                      {e.asset_code}
                    </button>
                  )}
                </td>
                <td className="px-2 py-0.5 text-muted">{KIND_LABEL[e.kind]}</td>
                <td className="px-2 py-0.5">
                  {e.to_status && (
                    <span className="mr-1 inline-block size-1.5 rounded-full" style={{ background: STATUS[e.to_status].color }} />
                  )}
                  {describe(e)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
