"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Schemas } from "@/lib/api";
import { formatMinutes } from "@/lib/domain";

/** Categorical slots 1-3 of the validated dark palette (dataviz reference; checked against
 *  the panel surface #10151b: lightness band, chroma, CVD and contrast all pass). */
export const POLICY_COLOR: Record<string, string> = {
  CRITICAL_FIRST: "#3987e5",
  MAX_RESTORATION: "#d95926",
  BALANCED: "#199e70",
};
export const POLICY_LABEL: Record<string, string> = {
  CRITICAL_FIRST: "Critical services first",
  MAX_RESTORATION: "Maximum restoration",
  BALANCED: "Balanced",
};
const BASELINE = "#8b97a6";
const INK = "#8b97a6";
const GRID = "#1f2731";

type Point = Schemas["TimelinePoint"];

/** Step series sampled on a shared time grid so one tooltip shows every strategy at t. */
function sample(series: Record<string, Point[]>, horizon: number) {
  const times = new Set<number>([0, horizon]);
  for (const pts of Object.values(series)) for (const p of pts) times.add(p.t_minutes);
  const sorted = [...times].sort((a, b) => a - b);
  return sorted.map((t) => {
    const row: Record<string, number> = { t };
    for (const [key, pts] of Object.entries(series)) {
      const last = pts.filter((p) => p.t_minutes <= t).at(-1);
      if (last) row[key] = last.impact_score;
    }
    return row;
  });
}

export function StrategyChart({ round }: { round: Schemas["StrategyRound"] }) {
  const horizon = Math.max(...round.strategies.map((s) => s.horizon_minutes));
  // Show the period where things change: up to the latest makespan plus a margin.
  // Rounded up to whole 6-hour steps so axis ticks land on readable times.
  const STEP = 360;
  const window = Math.min(
    horizon,
    Math.ceil((Math.max(360, ...round.strategies.map((s) => s.makespan_minutes)) * 1.25) / STEP) * STEP,
  );
  const tickStep = window > 8 * STEP ? 2 * STEP : STEP;
  const xTicks = Array.from({ length: Math.floor(window / tickStep) + 1 }, (_, i) => i * tickStep);
  const series: Record<string, Point[]> = {
    NO_ACTION: round.baseline_timeline as Point[],
    ...Object.fromEntries(round.strategies.map((s) => [s.policy, s.metrics.timeline])),
  };
  const data = sample(series, horizon).filter((r) => r.t <= window);

  return (
    <figure className="flex h-full flex-col" aria-label="Impact score over time by strategy">
      <figcaption className="px-3 pt-2 text-[13px] text-muted">
        Impact score over time <span className="text-dim">(lower is better; dashed = no recovery action)</span>
      </figcaption>
      <div className="min-h-0 flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 24, bottom: 4, left: -16 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="t" type="number" domain={[0, window]} ticks={xTicks} tickFormatter={(v: number) => formatMinutes(v)}
              stroke={INK} tick={{ fontSize: 13, fill: INK }} tickLine={false} axisLine={{ stroke: GRID }} />
            <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} stroke={INK} tick={{ fontSize: 13, fill: INK }}
              tickLine={false} axisLine={false} />
            <Tooltip
              cursor={{ stroke: INK, strokeDasharray: "3 3" }}
              contentStyle={{ background: "var(--color-raised)", border: "1px solid var(--color-line-strong)", borderRadius: 4, fontSize: 13 }}
              labelStyle={{ color: "var(--color-fg)" }}
              itemStyle={{ color: "var(--color-fg)" }}
              labelFormatter={(v) => formatMinutes(Number(v))}
              formatter={(value, name) => [Number(value).toFixed(2), name === "NO_ACTION" ? "No action" : POLICY_LABEL[String(name)]]}
            />
            <Legend
              verticalAlign="top"
              height={22}
              iconType="plainline"
              wrapperStyle={{ fontSize: 13, color: "var(--color-muted)" }}
              formatter={(name) => (name === "NO_ACTION" ? "No action" : POLICY_LABEL[String(name)])}
            />
            <Line type="stepAfter" dataKey="NO_ACTION" stroke={BASELINE} strokeWidth={1.5} strokeDasharray="4 3"
              dot={false} isAnimationActive={false} />
            {round.strategies.map((s) => (
              <Line key={s.id} type="stepAfter" dataKey={s.policy} stroke={POLICY_COLOR[s.policy]} strokeWidth={2}
                dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
