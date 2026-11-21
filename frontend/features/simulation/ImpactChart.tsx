"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Schemas } from "@/lib/api";
import { formatMinutes, formatNumber } from "@/lib/domain";

const LINE = "#58a6ff";
const INK_MUTED = "#8b97a6";
const GRID = "#1f2731";

interface Props {
  timeline: Schemas["TimelinePoint"][];
  horizon: number;
  currentT: number;
}

/** Impact score (0-100) over simulated time. One series, one axis; failed count in tooltip. */
export function ImpactChart({ timeline, horizon, currentT }: Props) {
  // The engine records a baseline point and a post-event point at the same t; keep the last
  // point per t, and extend the final value to the horizon so the step reads correctly.
  const byT = new Map<number, Schemas["TimelinePoint"]>();
  for (const p of timeline) byT.set(p.t_minutes, p);
  const points = [...byT.values()];
  const last = points[points.length - 1];
  if (last && last.t_minutes < horizon) points.push({ ...last, t_minutes: horizon });

  return (
    <figure className="flex h-full flex-col" aria-label="Impact score over time">
      <figcaption className="px-3 pt-2 text-[11px] text-muted">
        Impact score over time <span className="text-dim">(0 = no impact, 100 = total loss)</span>
      </figcaption>
      <div className="min-h-0 flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 8, right: 16, bottom: 4, left: -16 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis
              dataKey="t_minutes"
              type="number"
              domain={[0, horizon]}
              tickFormatter={(v: number) => formatMinutes(v)}
              stroke={INK_MUTED}
              tick={{ fontSize: 10, fill: INK_MUTED }}
              tickLine={false}
              axisLine={{ stroke: GRID }}
            />
            <YAxis
              domain={[0, 100]}
              ticks={[0, 25, 50, 75, 100]}
              stroke={INK_MUTED}
              tick={{ fontSize: 10, fill: INK_MUTED }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              cursor={{ stroke: INK_MUTED, strokeDasharray: "3 3" }}
              contentStyle={{
                background: "var(--color-raised)",
                border: "1px solid var(--color-line-strong)",
                borderRadius: 4,
                fontSize: 12,
              }}
              labelStyle={{ color: "var(--color-fg)" }}
              labelFormatter={(v) => formatMinutes(Number(v))}
              formatter={(value, _name, item) => {
                const p = item.payload as Schemas["TimelinePoint"];
                return [
                  `${Number(value).toFixed(2)} · ${p.failed} failed · ${formatNumber(p.affected_population)} people affected`,
                  "Impact",
                ];
              }}
            />
            <ReferenceLine x={currentT} stroke="#d8dee6" strokeOpacity={0.5} strokeDasharray="2 2" />
            <Line
              type="stepAfter"
              dataKey="impact_score"
              stroke={LINE}
              strokeWidth={2}
              dot={{ r: 3, fill: LINE, stroke: "var(--color-panel)", strokeWidth: 2 }}
              activeDot={{ r: 5 }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
