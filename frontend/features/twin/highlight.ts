import type { Schemas } from "@/lib/api";

/** Visual role of an asset relative to the current selection and filters. */
export type NodeRole = "selected" | "upstream" | "downstream" | "dimmed" | "hidden" | "normal";

export interface Highlight {
  selected: string | null;
  /** Everything the selected asset transitively depends on (from the API traversal). */
  upstream: ReadonlySet<string>;
  /** Everything that transitively depends on the selected asset (from the API traversal). */
  downstream: ReadonlySet<string>;
  /** Assets matching the active filters; null when no filter is active. */
  visible: ReadonlySet<string> | null;
  /** Dim assets outside the selection's chain (default true; the Lab keeps them visible). */
  dimUnrelated?: boolean;
}

export const NO_HIGHLIGHT: Highlight = {
  selected: null,
  upstream: new Set(),
  downstream: new Set(),
  visible: null,
};

/**
 * The selection's dependency chain always stays visible; filters only hide unrelated assets.
 * Precedence: selected > upstream > downstream > hidden (filtered out) > dimmed > normal.
 */
export function roleOf(code: string, h: Highlight): NodeRole {
  if (code === h.selected) return "selected";
  if (h.upstream.has(code)) return "upstream";
  if (h.downstream.has(code)) return "downstream";
  if (h.visible && !h.visible.has(code)) return "hidden";
  return h.selected === null || h.dimUnrelated === false ? "normal" : "dimmed";
}

/** Edges are emphasised when both ends are in the selection's dependency chain. */
export function edgeIsInChain(edge: Schemas["DependencyEdge"], h: Highlight): boolean {
  if (h.selected === null) return false;
  const up = (c: string) => c === h.selected || h.upstream.has(c);
  const down = (c: string) => c === h.selected || h.downstream.has(c);
  return (up(edge.provider) && up(edge.dependent)) || (down(edge.provider) && down(edge.dependent));
}

export function isAccessEdge(edge: Schemas["DependencyEdge"]): boolean {
  return edge.service_type === "ACCESS";
}
