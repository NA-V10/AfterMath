"use client";

import { CheckCircle2, XCircle } from "lucide-react";
import type { ReactNode } from "react";

import { Badge, SectionLabel, Stat, cn } from "@/components/ui/primitives";
import { formatMinutes, formatNumber } from "@/lib/domain";
import type { StrategyDetail } from "@/lib/queries";

import { GovernancePanel } from "./GovernancePanel";
import { strategyStatus } from "./status";
import { POLICY_COLOR, POLICY_LABEL } from "./StrategyChart";

const TYPE_LABEL: Record<string, string> = {
  REPAIR: "Repair",
  REPLACE: "Replace",
  DEPLOY_MOBILE_GENERATOR: "Mobile generator",
  REFUEL_BACKUP: "Refuel backup",
};

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-line px-3 py-2.5">
      <SectionLabel>{title}</SectionLabel>
      {children}
    </section>
  );
}

/** Action timeline: one row per action, bar positioned on the plan's time axis. */
function Gantt({ s }: { s: StrategyDetail }) {
  const end = Math.max(60, ...s.actions.map((a) => a.end_minutes));
  const ticks = Array.from({ length: 5 }, (_, i) => Math.round((end * i) / 4));
  const color = POLICY_COLOR[s.policy];
  return (
    <div data-testid="strategy-gantt">
      <div className="ml-[184px] flex justify-between text-[10px] text-dim">
        {ticks.map((t) => <span key={t}>{formatMinutes(t)}</span>)}
      </div>
      <ul className="flex flex-col gap-1">
        {s.actions.map((a) => {
          const temporary = a.action_type === "DEPLOY_MOBILE_GENERATOR" || a.action_type === "REFUEL_BACKUP";
          return (
            <li key={a.seq} className="flex items-center gap-2 text-[11px]">
              <span className="w-[176px] shrink-0 truncate" title={a.rationale}>
                <span className="font-mono text-dim">{a.seq}.</span> {TYPE_LABEL[a.action_type]}{" "}
                <span className="font-mono">{a.target_asset_code}</span>
              </span>
              <span className="relative h-4 flex-1 rounded-sm bg-raised">
                <span
                  className={cn("absolute top-0 h-4 rounded-sm", temporary && "opacity-60")}
                  style={{
                    left: `${(a.start_minutes / end) * 100}%`,
                    width: `${Math.max(0.8, ((a.end_minutes - a.start_minutes) / end) * 100)}%`,
                    backgroundColor: color,
                    backgroundImage: temporary ? "repeating-linear-gradient(45deg, transparent 0 3px, rgb(0 0 0 / .35) 3px 5px)" : undefined,
                  }}
                  title={`${formatMinutes(a.start_minutes)} → ${formatMinutes(a.end_minutes)}`}
                />
              </span>
              <span className="w-24 shrink-0 text-right font-mono text-[10px] text-dim">
                {formatMinutes(a.start_minutes)}–{formatMinutes(a.end_minutes).replace("T+", "")}
              </span>
            </li>
          );
        })}
      </ul>
      <p className="mt-1 text-[10px] text-dim">Hatched bars: temporary power. Hover a row for the scheduler&apos;s reason.</p>
    </div>
  );
}

export function StrategyDetailView({ s, incidentId }: { s: StrategyDetail; incidentId: string }) {
  const report = s.validation_report;
  const consumption = Object.entries(s.metrics.consumption);
  return (
    <div className="flex flex-col" data-testid="strategy-detail">
      <header className="flex flex-wrap items-center gap-2 px-3 pt-3 pb-2">
        <span className="size-2.5 rounded-full" style={{ background: POLICY_COLOR[s.policy] }} />
        <h3 className="font-semibold">{POLICY_LABEL[s.policy]}</h3>
        <Badge color={strategyStatus(s.status).color}>
          <span data-testid="strategy-status">{strategyStatus(s.status).label}</span>
        </Badge>
        {s.recommended && <Badge color="#58a6ff">recommended</Badge>}
        <span className="text-[11px] text-dim">round {s.planning_round} · inventory v{s.inventory_version} · hash {s.content_hash.slice(0, 10)}…</span>
      </header>
      <p className="px-3 pb-2 text-[12px] text-muted">{s.objective}</p>
      {s.rationale && (
        <p className="px-3 pb-2 text-[12px] leading-relaxed">
          {s.rationale} <span className="text-[10px] text-dim">— STRATEGIST ({s.rationale_source})</span>
        </p>
      )}
      {s.identical_to.length > 0 && (
        <p className="px-3 pb-2 text-[12px] text-focus">
          Same plan as {s.identical_to.map((p) => POLICY_LABEL[p]).join(" and ")}: the policies agree for this incident.
        </p>
      )}
      <Section title={`Actions (${s.actions.length})`}>
        {s.actions.length === 0 ? <p className="text-dim">No action could be scheduled.</p> : <Gantt s={s} />}
      </Section>
      <div className="grid gap-px bg-line md:grid-cols-2">
        <div className="bg-bg">
          <Section title="Benefits">
            <ul className="list-disc pl-4 text-[12px]">
              {s.benefits.length ? s.benefits.map((b) => <li key={b}>{b}</li>) : <li className="text-dim">None stands out against the alternatives.</li>}
            </ul>
          </Section>
        </div>
        <div className="bg-bg">
          <Section title="Limitations">
            <ul className="list-disc pl-4 text-[12px] text-warn">
              {s.limitations.length ? s.limitations.map((l) => <li key={l}>{l}</li>) : <li className="text-dim">None identified.</li>}
            </ul>
          </Section>
        </div>
      </div>
      <Section title="Resources">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="Cost" value={formatNumber(s.total_cost)} />
          <Stat label="Risk" value={s.risk_score.toFixed(1)} />
          {Object.entries(s.metrics.crew_minutes).map(([trade, m]) => (
            <Stat key={trade} label={`${trade.toLowerCase()} crew`} value={`${(m / 60).toFixed(1)} h`} />
          ))}
        </div>
        {consumption.length > 0 && (
          <table className="mt-2 w-full text-left text-[11px]">
            <thead className="text-[10px] uppercase tracking-[0.08em] text-dim">
              <tr><th className="font-medium">Consumable</th><th className="text-right font-medium">Used</th><th className="text-right font-medium">Left</th></tr>
            </thead>
            <tbody className="font-mono">
              {consumption.map(([k, v]) => (
                <tr key={k} className="border-t border-line">
                  <td className="font-sans">{k.replaceAll("_", " ")}</td>
                  <td className="text-right">{formatNumber(v)}</td>
                  <td className={cn("text-right", s.metrics.remaining[k] === 0 && "text-warn")}>{formatNumber(s.metrics.remaining[k])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
      {s.unschedulable.filter((u) => u.reason !== "NO_BENEFIT").length > 0 && (
        <Section title="Could not be scheduled">
          <ul className="text-[12px] text-warn">
            {s.unschedulable.filter((u) => u.reason !== "NO_BENEFIT").map((u) => (
              <li key={u.key}><span className="font-mono">{u.key}</span> — {u.reason.replaceAll("_", " ").toLowerCase()} ({u.detail})</li>
            ))}
          </ul>
        </Section>
      )}
      <Section title="GUARDIAN validation">
        {!report ? (
          <p className="text-dim">Not validated.</p>
        ) : (
          <ul className="flex flex-col gap-0.5 text-[12px]" data-testid="validation-rules">
            {report.rules.map((r) => (
              <li key={r.rule} className="flex items-start gap-1.5">
                {r.passed ? <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-ok" /> : <XCircle className="mt-0.5 size-3.5 shrink-0 text-crit" />}
                <span><span className="font-mono">{r.rule}</span> {r.description}
                  {r.findings.length > 0 && <span className="block text-[11px] text-crit">{r.findings.join("; ")}</span>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="Approval and execution">
        <GovernancePanel s={s} incidentId={incidentId} />
      </Section>
    </div>
  );
}
