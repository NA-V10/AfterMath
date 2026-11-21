"use client";

import { ArrowDownRight, ArrowUpLeft } from "lucide-react";
import type { ReactNode } from "react";

import { Badge, ErrorState, Loading, SectionLabel, Stat } from "@/components/ui/primitives";
import type { Schemas } from "@/lib/api";
import { CATEGORY, CONDITION, SERVICE_LABEL, categoryColor, formatNumber } from "@/lib/domain";
import { useAsset, useCriticality, useTraversal } from "@/lib/queries";

import { DOWNSTREAM_COLOR, UPSTREAM_COLOR } from "./mapData";

function AssetLink({ asset, onSelect }: { asset: Schemas["AssetRef"]; onSelect: (c: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(asset.code)}
      className="inline-flex items-center gap-1 rounded-sm px-1 hover:bg-raised"
      title={asset.name}
    >
      <span className="size-1.5 rounded-full" style={{ background: categoryColor(asset.category) }} />
      <span className="font-mono text-[11px]">{asset.code}</span>
    </button>
  );
}

function Section({ title, children }: { title: ReactNode; children: ReactNode }) {
  return (
    <section className="border-t border-line px-3 py-2.5">
      <SectionLabel>{title}</SectionLabel>
      {children}
    </section>
  );
}

function StructuralCriticality({ code, onSelect }: { code: string; onSelect: (c: string) => void }) {
  const q = useCriticality();
  if (q.isPending) return <div className="text-dim">Running N-1 analysis…</div>;
  if (q.isError) return <div className="text-crit">Could not load structural criticality.</div>;
  const entry = q.data.entries.find((e) => e.code === code);
  if (!entry) return <div className="text-dim">Not applicable to demand zones.</div>;
  const rank = q.data.entries.findIndex((e) => e.code === code) + 1;
  return (
    <div className="flex flex-col gap-1.5" data-testid="structural-criticality">
      <div className="flex flex-wrap items-center gap-2">
        <span>
          Impact if lost: <span className="font-mono">{entry.impact_score.toFixed(2)}</span>{" "}
          <span className="text-dim">(rank {rank} of {q.data.entries.length})</span>
        </span>
        {entry.single_point_of_failure && <Badge color="#f85149">single point of failure</Badge>}
      </div>
      {entry.critical_failed.length > 0 && (
        <div className="text-[11px] text-muted">
          Losing it alone fails critical assets:{" "}
          {entry.critical_failed.map((c) => (
            <button key={c} type="button" onClick={() => onSelect(c)} className="mr-1 font-mono hover:underline">{c}</button>
          ))}
        </div>
      )}
      <div className="text-[11px] text-dim">
        {entry.failed_assets.length} other asset(s) fail within {q.data.horizon_minutes / 60} h ·{" "}
        {formatNumber(entry.affected_population)} people affected · exact N-1 simulation
      </div>
    </div>
  );
}

function Reach({
  code,
  direction,
  onSelect,
}: {
  code: string;
  direction: "upstream" | "downstream";
  onSelect: (c: string) => void;
}) {
  const q = useTraversal(code, direction);
  if (q.isPending) return <div className="text-dim">Loading…</div>;
  if (q.isError) return <div className="text-crit">Could not load {direction} reach.</div>;
  if (q.data.items.length === 0) return <div className="text-dim">None.</div>;
  const byDepth = new Map<number, Schemas["TraversalItem"][]>();
  for (const item of q.data.items) byDepth.set(item.depth, [...(byDepth.get(item.depth) ?? []), item]);
  return (
    <div className="flex flex-col gap-1">
      {[...byDepth.entries()].map(([depth, items]) => (
        <div key={depth} className="flex gap-2">
          <span className="w-6 shrink-0 pt-px text-right font-mono text-[10px] text-dim">{depth}</span>
          <div className="flex flex-wrap gap-0.5">
            {items.map((i) => (
              <AssetLink key={i.asset.code} asset={i.asset} onSelect={onSelect} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export function AssetInspector({
  code,
  onSelect,
  headerActions,
}: {
  code: string;
  onSelect: (c: string) => void;
  headerActions?: ReactNode;
}) {
  const q = useAsset(code);
  if (q.isPending) return <Loading label={`Loading ${code}`} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const a = q.data;
  const condition = CONDITION[a.condition];
  const facts: [string, ReactNode][] = [
    ["Capacity", a.capacity !== null ? `${formatNumber(a.capacity, 1)} ${a.capacity_unit ?? ""}` : "—"],
    ["Utilisation", a.utilization !== null ? `${Math.round(a.utilization * 100)}%` : "—"],
    ["Elevation", a.elevation_m !== null ? `${a.elevation_m} m` : "—"],
    ["Backup power", a.backup_power_hours ? `${a.backup_power_hours} h` : "none"],
  ];
  if (a.population_served) facts.push(["Population", formatNumber(a.population_served)]);
  if (a.is_source) facts.push(["Role", "source"]);

  return (
    <div className="flex h-full flex-col overflow-y-auto" data-testid="asset-inspector">
      <header className="flex items-start justify-between gap-2 px-3 pt-3 pb-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span
              className="flex size-5 items-center justify-center rounded-[3px] font-mono text-[10px] font-bold text-bg"
              style={{ background: categoryColor(a.category) }}
              aria-hidden
            >
              {CATEGORY[a.category].glyph}
            </span>
            <h2 className="font-mono text-[15px] font-semibold">{a.code}</h2>
          </div>
          <div className="mt-0.5 truncate">{a.name}</div>
          <div className="mt-1.5 flex flex-wrap gap-1">
            <Badge>{CATEGORY[a.category].label}</Badge>
            <Badge color={condition.color}>{condition.label}</Badge>
            <Badge>synthetic</Badge>
          </div>
        </div>
        {headerActions}
      </header>

      <div className="px-3 pb-2.5">
        <div className="mb-1 flex items-center justify-between text-[10px] uppercase tracking-[0.08em] text-dim">
          <span>Criticality</span>
          <span className="font-mono text-[12px] text-fg">{a.criticality}</span>
        </div>
        <div className="h-1 rounded-full bg-raised" role="meter" aria-valuenow={a.criticality} aria-valuemin={0} aria-valuemax={100} aria-label="Criticality">
          <div className="h-1 rounded-full bg-fg/70" style={{ width: `${a.criticality}%` }} />
        </div>
        <div className="mt-2.5 grid grid-cols-2 gap-2">
          {facts.map(([label, value]) => (
            <Stat key={label} label={label} value={value} />
          ))}
        </div>
      </div>

      <Section title={`Depends on · ${a.requirements.length} requirement${a.requirements.length === 1 ? "" : "s"}`}>
        {a.requirements.length === 0 ? (
          <div className="text-dim">No upstream requirements{a.is_source ? " (source asset)" : ""}.</div>
        ) : (
          <ul className="flex flex-col gap-2">
            {a.requirements.map((g) => (
              <li key={g.group} className="rounded-sm border border-line bg-panel-2 p-2">
                <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                  <span className="font-medium text-fg">{SERVICE_LABEL[g.service_type] ?? g.service_type}</span>
                  <span className={g.mode === "HARD" ? "text-fg" : "text-muted"}>
                    {g.mode === "HARD" ? "required" : "supporting"}
                  </span>
                  <span className="text-dim">
                    needs {g.min_required} of {g.providers.length}
                  </span>
                  {g.mode === "HARD" && g.service_type !== "ACCESS" && (
                    <span className={g.spare_providers === 0 ? "text-warn" : "text-ok"}>
                      {g.spare_providers === 0 ? "no redundancy" : `${g.spare_providers} spare`}
                    </span>
                  )}
                </div>
                <div className="mt-1 flex flex-wrap gap-0.5">
                  {g.providers.map((p) => (
                    <AssetLink key={p.code} asset={p} onSelect={onSelect} />
                  ))}
                </div>
                <p className="mt-1 text-[11px] text-muted">{g.description}</p>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={`Supports · ${a.dependents.length} direct dependent${a.dependents.length === 1 ? "" : "s"}`}>
        {a.dependents.length === 0 ? (
          <div className="text-dim">Nothing depends on this asset.</div>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {a.dependents.map((d) => (
              <li key={`${d.asset.code}-${d.service_type}`} className="flex items-center gap-1.5 text-[11px]">
                <AssetLink asset={d.asset} onSelect={onSelect} />
                <span className="text-muted">{SERVICE_LABEL[d.service_type] ?? d.service_type}</span>
                <span className="text-dim">{d.mode === "HARD" ? "required" : "supporting"}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section
        title={
          <span className="flex items-center gap-1" style={{ color: UPSTREAM_COLOR }}>
            <ArrowUpLeft className="size-3" aria-hidden /> Upstream reach · {a.upstream_count}
          </span>
        }
      >
        <Reach code={a.code} direction="upstream" onSelect={onSelect} />
      </Section>
      <Section
        title={
          <span className="flex items-center gap-1" style={{ color: DOWNSTREAM_COLOR }}>
            <ArrowDownRight className="size-3" aria-hidden /> Downstream reach · {a.downstream_count}
          </span>
        }
      >
        <Reach code={a.code} direction="downstream" onSelect={onSelect} />
        <p className="mt-2 text-[11px] text-dim">
          Structural reach only: redundancy and backup power determine what actually fails (see
          structural criticality below).
        </p>
      </Section>

      <Section title="Structural criticality">
        <StructuralCriticality code={a.code} onSelect={onSelect} />
      </Section>

      {a.recovery_profile && (
        <Section title="Recovery profile">
          <div className="grid grid-cols-2 gap-2">
            <Stat label="Trade" value={a.recovery_profile.trade.toLowerCase()} />
            <Stat label="Crew" value={a.recovery_profile.crew_size} />
            <Stat label="Repair" value={`${a.recovery_profile.repair_minutes / 60} h`} />
            <Stat label="Replace" value={`${a.recovery_profile.replace_minutes / 60} h`} />
            <Stat label="Repair cost" value={formatNumber(a.recovery_profile.cost)} />
            <Stat
              label="Parts"
              value={
                Object.entries(a.recovery_profile.parts ?? {})
                  .map(([k, v]) => `${v}× ${k.replaceAll("_", " ")}`)
                  .join(", ") || "—"
              }
            />
          </div>
        </Section>
      )}

      {Object.keys(a.metadata).length > 1 && (
        <Section title="Notes">
          <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-[11px]">
            {Object.entries(a.metadata)
              .filter(([k]) => k !== "synthetic")
              .map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-dim">{k}</dt>
                  <dd className="text-muted">{Array.isArray(v) ? v.join(", ") : String(v)}</dd>
                </div>
              ))}
          </dl>
        </Section>
      )}
    </div>
  );
}
