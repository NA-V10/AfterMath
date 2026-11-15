import { describe, expect, it } from "vitest";

import type { Schemas } from "@/lib/api";

import { type Highlight, NO_HIGHLIGHT, edgeIsInChain, roleOf } from "./highlight";
import { assetFeatures, featureStates, selectionLinks } from "./mapData";

const h = (over: Partial<Highlight>): Highlight => ({ ...NO_HIGHLIGHT, ...over });

const node = (code: string, x = 0): Schemas["GraphNode"] => ({
  code,
  name: `Asset ${code}`,
  category: "SUBSTATION",
  condition: "INTACT",
  criticality: 50,
  position: [x, 0],
  geometry: { type: "Point", coordinates: [x, 0] },
  population_served: null,
  component: 0,
});

const edge = (provider: string, dependent: string, service_type: Schemas["DependencyEdge"]["service_type"] = "POWER"): Schemas["DependencyEdge"] => ({
  provider,
  dependent,
  service_type,
  mode: "HARD",
  redundancy_group: "power",
  min_required: 1,
  description: "test",
});

describe("roleOf", () => {
  it("is normal with no selection and no filter", () => {
    expect(roleOf("A-01", NO_HIGHLIGHT)).toBe("normal");
  });

  it("classifies the chain around a selection", () => {
    const hl = h({ selected: "B-01", upstream: new Set(["A-01"]), downstream: new Set(["C-01"]) });
    expect(roleOf("B-01", hl)).toBe("selected");
    expect(roleOf("A-01", hl)).toBe("upstream");
    expect(roleOf("C-01", hl)).toBe("downstream");
    expect(roleOf("Z-99", hl)).toBe("dimmed");
  });

  it("never hides the selection's chain, even when filtered out", () => {
    const hl = h({
      selected: "B-01",
      upstream: new Set(["A-01"]),
      downstream: new Set(["C-01"]),
      visible: new Set(["B-01"]),
    });
    expect(roleOf("A-01", hl)).toBe("upstream");
    expect(roleOf("C-01", hl)).toBe("downstream");
    expect(roleOf("Z-99", hl)).toBe("hidden");
  });

  it("hides filtered-out assets when nothing is selected", () => {
    expect(roleOf("A-01", h({ visible: new Set(["B-01"]) }))).toBe("hidden");
    expect(roleOf("B-01", h({ visible: new Set(["B-01"]) }))).toBe("normal");
  });
});

describe("edgeIsInChain", () => {
  const hl = h({ selected: "B-01", upstream: new Set(["A-01"]), downstream: new Set(["C-01"]) });
  it("includes edges along the upstream and downstream chains", () => {
    expect(edgeIsInChain(edge("A-01", "B-01"), hl)).toBe(true);
    expect(edgeIsInChain(edge("B-01", "C-01"), hl)).toBe(true);
  });
  it("excludes edges that only touch the chain", () => {
    expect(edgeIsInChain(edge("A-01", "Z-99"), hl)).toBe(false);
    expect(edgeIsInChain(edge("Z-99", "C-01"), hl)).toBe(false);
  });
});

describe("map data", () => {
  const nodes = [node("A-01", 0), node("B-01", 1), node("C-01", 2)];
  const edges = [edge("A-01", "B-01"), edge("B-01", "C-01"), edge("A-01", "C-01", "ACCESS")];

  it("keeps every API asset and its code as feature id", () => {
    const fc = assetFeatures(nodes);
    expect(fc.features.map((f) => f.id)).toEqual(["A-01", "B-01", "C-01"]);
  });

  it("draws links only for the selection's direct edges, excluding access unless asked", () => {
    expect(selectionLinks(nodes, edges, null, false).features).toHaveLength(0);
    const links = selectionLinks(nodes, edges, "B-01", false).features;
    expect(links.map((l) => l.properties?.kind).sort()).toEqual(["down", "up"]);
    expect(selectionLinks(nodes, edges, "C-01", true).features).toHaveLength(2);
    expect(selectionLinks(nodes, edges, "C-01", false).features).toHaveLength(1);
  });

  it("derives feature-state from the same roles as the graph", () => {
    const hl = h({ selected: "B-01", upstream: new Set(["A-01"]), downstream: new Set() });
    const states = featureStates(nodes, hl);
    expect(states.get("B-01")).toMatchObject({ sel: true, dim: false });
    expect(states.get("A-01")).toMatchObject({ up: true, dim: false });
    expect(states.get("C-01")).toMatchObject({ dim: true, up: false, down: false });
  });
});
