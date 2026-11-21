"use client";

import { AlertTriangle, CheckCircle2, ShieldAlert } from "lucide-react";
import type { ReactNode } from "react";

import { Badge, SectionLabel, Stat } from "@/components/ui/primitives";
import { STATUS, formatNumber } from "@/lib/domain";
import type { AgentExecution } from "@/lib/queries";

/* Output shapes come from the backend's agent schemas (app/agents/schemas.py). */
type Out = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

function Codes({ codes }: { codes: string[] }) {
  return codes.length ? <span className="font-mono text-[11px]">{codes.join(", ")}</span> : <span className="text-dim">none</span>;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-line px-3 py-2.5">
      <SectionLabel>{title}</SectionLabel>
      {children}
    </section>
  );
}

function SentinelView({ o }: { o: Out }) {
  const damaged = o.affected_assets.filter((m: Out) => m.role === "damaged");
  const affected = o.affected_assets.filter((m: Out) => m.role === "affected");
  return (
    <>
      <div className="grid grid-cols-3 gap-2 px-3 pb-2">
        <Stat label="Type" value={o.incident_type.replace("_", " ").toLowerCase()} />
        <Stat label="Severity" value={o.severity.toLowerCase()} />
        <Stat label="Confidence" value={o.confidence.toFixed(2)} />
      </div>
      <Section title="Damaged facilities (become initiating events)">
        <ul className="flex flex-col gap-1">
          {damaged.length === 0 && <li className="text-dim">None identified.</li>}
          {damaged.map((m: Out) => (
            <li key={m.code} className="text-[12px]">
              <span className="font-mono">{m.code}</span> {m.name} <span className="text-dim">· {m.condition.toLowerCase()} · {m.method} match {m.score.toFixed(2)}</span>
              <div className="text-[11px] text-muted">“{m.quote}”</div>
            </li>
          ))}
        </ul>
      </Section>
      {affected.length > 0 && (
        <Section title="Mentioned as affected (evidence only)">
          <Codes codes={affected.map((m: Out) => m.code)} />
        </Section>
      )}
      {o.missing_information.length > 0 && (
        <Section title="Missing information">
          <ul className="list-disc pl-4 text-[12px] text-warn">
            {o.missing_information.map((m: string) => <li key={m}>{m}</li>)}
          </ul>
        </Section>
      )}
      {o.reported_consequences.length > 0 && (
        <Section title="Reported consequences (not authoritative)">
          <ul className="list-disc pl-4 text-[12px] text-muted">
            {o.reported_consequences.map((c: string) => <li key={c}>{c}</li>)}
          </ul>
        </Section>
      )}
    </>
  );
}

function CartographerView({ o }: { o: Out }) {
  const lost = o.redundancy_effects.filter((r: Out) => r.effect === "REQUIREMENT_LOST");
  const support = o.redundancy_effects.filter((r: Out) => r.effect === "SUPPORT_LOST");
  const reduced = o.redundancy_effects.filter((r: Out) => r.effect === "REDUNDANCY_REDUCED");
  return (
    <>
      <p className="px-3 pb-2 text-[12px] leading-relaxed">{o.briefing}</p>
      <Section title={`Downstream assets (${o.downstream.length})`}>
        <Codes codes={o.downstream.map((d: Out) => d.code)} />
      </Section>
      <Section title="Single points of failure">
        {o.single_points_of_failure.length === 0 ? (
          <span className="text-dim">none among the damaged assets</span>
        ) : (
          o.single_points_of_failure.map((s: Out) => (
            <div key={s.code} className="text-[12px]">
              <span className="font-mono">{s.code}</span> alone fails <Codes codes={s.critical_failed} />
            </div>
          ))
        )}
      </Section>
      <Section title="Redundancy">
        <div className="text-[12px]">Required supply lost: <Codes codes={lost.map((r: Out) => r.dependent)} /></div>
        <div className="text-[12px]">Supporting service lost (still operating): <Codes codes={support.map((r: Out) => r.dependent)} /></div>
        <div className="text-[12px]">No spare left: <Codes codes={reduced.map((r: Out) => r.dependent)} /></div>
      </Section>
    </>
  );
}

function OracleView({ o }: { o: Out }) {
  return (
    <>
      <p className="px-3 pb-2 text-[12px] leading-relaxed">{o.narrative}</p>
      <div className="grid grid-cols-4 gap-2 px-3 pb-2">
        <Stat label="Impact" value={o.impact_score.toFixed(2)} />
        <Stat label="Failed" value={<span style={{ color: o.failed ? STATUS.FAILED.color : undefined }}>{o.failed}</span>} />
        <Stat label="On backup" value={o.on_backup} />
        <Stat label="People" value={formatNumber(o.affected_population)} />
      </div>
      <Section title="Critical failure chains">
        <ul className="flex flex-col gap-0.5 font-mono text-[11px]">
          {o.key_chains.map((c: Out) => (
            <li key={c.asset}>
              <span style={{ color: STATUS[c.status as keyof typeof STATUS]?.color }}>{c.asset}</span> ← {c.chain.slice(1).join(" ← ")}
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Backup power deadlines">
        <ul className="flex flex-col gap-0.5 text-[12px]">
          {o.deadlines.map((d: Out) => (
            <li key={d.asset} className={d.exhausted_within_horizon ? "text-warn" : "text-muted"}>
              <span className="font-mono">{d.asset}</span> T+{d.exhausts_at_minutes} min{d.exhausted_within_horizon ? " (runs out)" : ""}
            </li>
          ))}
        </ul>
        <p className="mt-2 text-[11px] text-dim">Applied to the operational picture · result {o.result_hash.slice(0, 16)}…</p>
      </Section>
    </>
  );
}

export function ExecutionDetail({ execution }: { execution: AgentExecution }) {
  const o = execution.output as Out | null;
  const grounding = execution.grounding as Out | null;
  return (
    <div className="flex flex-col" data-testid={`execution-${execution.agent}`}>
      <header className="flex flex-wrap items-center gap-2 px-3 pt-3 pb-2">
        <h3 className="font-mono text-[14px] font-semibold">{execution.agent}</h3>
        <Badge>attempt {execution.attempt}</Badge>
        <Badge color={execution.status === "FAILED" ? "#f85149" : execution.status === "FELL_BACK" ? "#d29922" : "#3fb950"}>
          {execution.status === "FELL_BACK" ? "deterministic fallback" : execution.status.toLowerCase()}
        </Badge>
        {grounding && (
          <Badge color={grounding.ok ? "#3fb950" : "#d29922"}>
            {grounding.ok ? <CheckCircle2 className="size-3" /> : <ShieldAlert className="size-3" />}
            {grounding.ok ? "grounded" : "LLM text rejected"}
          </Badge>
        )}
        {execution.latency_ms != null && <span className="text-[11px] text-dim">{Math.round(execution.latency_ms)} ms</span>}
      </header>
      {execution.summary && <p className="px-3 pb-2 text-[12px] text-muted">{execution.summary}</p>}
      {execution.error && (
        <p className="mx-3 mb-2 flex items-start gap-1.5 rounded-sm border border-crit/40 bg-crit/10 p-2 text-[12px] text-crit">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" /> {String((execution.error as Out).type)}: {String((execution.error as Out).message)}
        </p>
      )}
      {o && execution.agent === "SENTINEL" && <SentinelView o={o} />}
      {o && execution.agent === "CARTOGRAPHER" && <CartographerView o={o} />}
      {o && execution.agent === "ORACLE" && <OracleView o={o} />}
      {grounding && !grounding.ok && (
        <Section title="Grounding check">
          <p className="text-[12px] text-warn">
            The language model mentioned facts not present in the tool results
            {grounding.unknown_asset_codes.length > 0 && <> (assets: {grounding.unknown_asset_codes.join(", ")})</>}
            {grounding.unknown_numbers.length > 0 && <> (figures: {grounding.unknown_numbers.join(", ")})</>}; its text was
            discarded and the deterministic explanation is shown instead.
          </p>
        </Section>
      )}
      <Section title={`Deterministic tool calls (${execution.tool_calls.length})`}>
        <table className="w-full text-left text-[11px]">
          <tbody>
            {(execution.tool_calls as Out[]).map((t, i) => (
              <tr key={i} className="border-t border-line first:border-0">
                <td className="py-0.5 font-mono">{t.name}</td>
                <td className={t.ok ? "text-ok" : "text-crit"}>{t.ok ? "ok" : "error"}</td>
                <td className="text-right text-dim">{t.ms} ms</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
      <Section title={`Language model calls (${execution.llm_calls.length})`}>
        {(execution.llm_calls as Out[]).length === 0 && <span className="text-dim">none</span>}
        <ul className="flex flex-col gap-1 text-[11px]">
          {(execution.llm_calls as Out[]).map((c, i) => (
            <li key={i}>
              <span className="font-mono">{c.task}</span> → {c.provider}
              {c.model ? ` (${c.model})` : ""}
              {c.fell_back && <span className="text-warn"> · fell back</span>}
              {c.reason && <span className="text-warn"> · {String(c.reason).slice(0, 60)}</span>}
              {c.attempts && (
                <span className="text-dim"> · attempts: {(c.attempts as Out[]).map((a) => a.outcome).join(" → ")}</span>
              )}
            </li>
          ))}
        </ul>
        {(execution.tokens_in || execution.tokens_out) && (
          <p className="mt-1 text-[11px] text-dim">tokens in {execution.tokens_in ?? 0} · out {execution.tokens_out ?? 0}</p>
        )}
        <p className="mt-1 text-[11px] text-dim">Structured outputs and evidence only — no model reasoning is stored or shown.</p>
      </Section>
    </div>
  );
}
