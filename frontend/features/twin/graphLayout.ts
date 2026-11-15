import ELK from "elkjs/lib/elk.bundled.js";

import type { Schemas } from "@/lib/api";

import { isAccessEdge } from "./highlight";

export const NODE_WIDTH = 150;
export const NODE_HEIGHT = 34;

const elk = new ELK();

/**
 * Layered left-to-right layout: providers on the left, dependents on the right.
 * Deterministic for identical input (ELK is deterministic; inputs are sorted by code).
 */
export async function layoutGraph(
  nodes: Schemas["GraphNode"][],
  edges: Schemas["DependencyEdge"][],
  includeAccess: boolean,
): Promise<Map<string, { x: number; y: number }>> {
  const used = edges.filter((e) => includeAccess || !isAccessEdge(e));
  const result = await elk.layout({
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.layered.spacing.nodeNodeBetweenLayers": "56",
      "elk.spacing.nodeNode": "12",
      "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
      "elk.separateConnectedComponents": "true",
      "elk.spacing.componentComponent": "40",
    },
    children: [...nodes]
      .sort((a, b) => a.code.localeCompare(b.code))
      .map((n) => ({ id: n.code, width: NODE_WIDTH, height: NODE_HEIGHT })),
    edges: used.map((e) => ({
      id: `${e.provider}->${e.dependent}:${e.service_type}`,
      sources: [e.provider],
      targets: [e.dependent],
    })),
  });
  const positions = new Map<string, { x: number; y: number }>();
  for (const child of result.children ?? []) {
    positions.set(child.id, { x: child.x ?? 0, y: child.y ?? 0 });
  }
  return positions;
}
