"use client";

import { Search, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Dot, IconButton, SectionLabel, cn } from "@/components/ui/primitives";
import type { Schemas } from "@/lib/api";
import { CATEGORY, DOMAIN_COLOR, DOMAIN_LABEL, categoriesByDomain, categoryColor } from "@/lib/domain";
import type { AssetCategory, AssetFilters } from "@/lib/queries";

interface Props {
  filters: AssetFilters;
  onChange: (filters: AssetFilters) => void;
  matches: Schemas["AssetSummary"][] | undefined;
  isFetching: boolean;
  selected: string | null;
  onSelect: (code: string) => void;
  showAccess: boolean;
  onShowAccess: (value: boolean) => void;
  categoryCounts: Map<AssetCategory, number>;
}

export function FilterPanel({
  filters,
  onChange,
  matches,
  isFetching,
  selected,
  onSelect,
  showAccess,
  onShowAccess,
  categoryCounts,
}: Props) {
  const [query, setQuery] = useState(filters.q);
  useEffect(() => {
    const t = setTimeout(() => {
      if (query !== filters.q) onChange({ ...filters, q: query });
    }, 250);
    return () => clearTimeout(t);
  }, [query, filters, onChange]);

  const toggleCategory = (c: AssetCategory) =>
    onChange({
      ...filters,
      categories: filters.categories.includes(c)
        ? filters.categories.filter((x) => x !== c)
        : [...filters.categories, c],
    });

  const active =
    filters.categories.length > 0 || filters.minCriticality > 0 || filters.q.trim() !== "";

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-3" data-testid="filter-panel">
      <label className="relative block">
        <span className="sr-only">Search assets by code or name</span>
        <Search className="pointer-events-none absolute top-1.5 left-2 size-3.5 text-dim" aria-hidden />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search code or name"
          className="w-full rounded-sm border border-line-strong bg-bg py-1 pr-2 pl-7 text-[12px] placeholder:text-dim focus:border-focus focus:outline-none"
        />
      </label>

      <div>
        <div className="flex items-center justify-between">
          <SectionLabel>Categories</SectionLabel>
          {active && (
            <button
              type="button"
              onClick={() => {
                setQuery("");
                onChange({ categories: [], conditions: [], minCriticality: 0, q: "" });
              }}
              className="mb-1.5 text-[11px] text-focus hover:underline"
            >
              Clear filters
            </button>
          )}
        </div>
        <div className="flex flex-col gap-2">
          {categoriesByDomain().map(([domain, categories]) => (
            <fieldset key={domain}>
              <legend className="mb-0.5 flex items-center gap-1.5 text-[11px] text-muted">
                <Dot color={DOMAIN_COLOR[domain]} />
                {DOMAIN_LABEL[domain]}
              </legend>
              {categories.map((c) => (
                <label key={c} className="flex cursor-pointer items-center gap-2 py-px pl-3.5 text-[12px] hover:text-fg">
                  <input
                    type="checkbox"
                    checked={filters.categories.includes(c)}
                    onChange={() => toggleCategory(c)}
                    className="accent-[#58a6ff]"
                  />
                  <span className="flex-1 text-muted">{CATEGORY[c].label}</span>
                  <span className="font-mono text-[11px] text-dim">{categoryCounts.get(c) ?? 0}</span>
                </label>
              ))}
            </fieldset>
          ))}
        </div>
      </div>

      <label className="block">
        <SectionLabel>Minimum criticality · {filters.minCriticality}</SectionLabel>
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          value={filters.minCriticality}
          onChange={(e) => onChange({ ...filters, minCriticality: Number(e.target.value) })}
          className="w-full accent-[#58a6ff]"
          aria-label="Minimum criticality"
        />
      </label>

      <label className="flex cursor-pointer items-center gap-2 text-[12px] text-muted">
        <input
          type="checkbox"
          checked={showAccess}
          onChange={(e) => onShowAccess(e.target.checked)}
          className="accent-[#58a6ff]"
        />
        Show road-access dependencies
      </label>

      <div className="min-h-0 flex-1">
        <SectionLabel>
          Assets {matches ? `(${matches.length})` : ""}
          {isFetching && <span className="ml-1 text-dim">…</span>}
        </SectionLabel>
        <ul className="flex flex-col" aria-label="Matching assets">
          {matches?.map((a) => (
            <li key={a.code}>
              <button
                type="button"
                onClick={() => onSelect(a.code)}
                aria-pressed={a.code === selected}
                className={cn(
                  "flex w-full items-center gap-2 rounded-sm px-1.5 py-0.5 text-left text-[12px] hover:bg-raised",
                  a.code === selected && "bg-raised text-fg",
                )}
              >
                <Dot color={categoryColor(a.category)} />
                <span className="w-14 shrink-0 font-mono text-[11px]">{a.code}</span>
                <span className="truncate text-muted">{a.name}</span>
              </button>
            </li>
          ))}
          {matches?.length === 0 && <li className="px-1.5 text-dim">No assets match.</li>}
        </ul>
      </div>
    </div>
  );
}

export function ClearSelectionButton({ onClear }: { onClear: () => void }) {
  return (
    <IconButton aria-label="Close inspector" onClick={onClear}>
      <X className="size-3.5" />
    </IconButton>
  );
}
