"use client";

import "@xyflow/react/dist/style.css";

import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  type Edge,
  type Node,
  type NodeProps,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import { memo, useEffect, useMemo, useState } from "react";

import { cn } from "@/components/ui/primitives";
import type { Schemas } from "@/lib/api";
import { CATEGORY, CONDITION, STATUS, categoryColor } from "@/lib/domain";
import type { FunctionalStatus } from "@/lib/queries";

import { NODE_HEIGHT, NODE_WIDTH, layoutGraph } from "./graphLayout";
import { type Highlight, type NodeRole, edgeIsInChain, isAccessEdge, roleOf } from "./highlight";
import { DOWNSTREAM_COLOR, SELECTED_COLOR, UPSTREAM_COLOR } from "./mapData";

type AssetNodeData = {
  code: string;
  name: string;
  category: Schemas["GraphNode"]["category"];
  condition: Schemas["GraphNode"]["condition"];
  role: NodeRole;
  status: FunctionalStatus | null;
};
type AssetNode = Node<AssetNodeData, "asset">;

const ROLE_BORDER: Partial<Record<NodeRole, string>> = {
  selected: SELECTED_COLOR,
  upstream: UPSTREAM_COLOR,
  downstream: DOWNSTREAM_COLOR,
};

const AssetNodeView = memo(function AssetNodeView({ data }: NodeProps<AssetNode>) {
  const border = ROLE_BORDER[data.role];
  return (
    <div
      data-testid={`graph-node-${data.code}`}
      data-role={data.role}
      data-status={data.status ?? undefined}
      title={`${data.code} — ${data.name}`}
      className={cn(
        "flex items-center gap-1.5 rounded-sm border bg-panel-2 px-1.5 text-[11px] transition-opacity",
        data.role === "dimmed" && "opacity-25",
        data.role === "hidden" && "opacity-[0.06]",
      )}
      style={{
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        borderColor: border ?? "var(--color-line-strong)",
        background:
          data.status && data.status !== "OPERATIONAL"
            ? `color-mix(in srgb, ${STATUS[data.status].color} 18%, var(--color-panel-2))`
            : undefined,
        boxShadow: data.role === "selected" ? `0 0 0 1px ${SELECTED_COLOR}` : undefined,
      }}
    >
      <Handle type="target" position={Position.Left} className="!size-1 !min-h-0 !min-w-0 !border-0 !bg-transparent" />
      <span
        aria-hidden
        className="flex size-5 shrink-0 items-center justify-center rounded-[3px] font-mono text-[10px] font-bold text-bg"
        style={{ background: categoryColor(data.category) }}
      >
        {CATEGORY[data.category].glyph}
      </span>
      <span className="min-w-0 flex-1 leading-tight">
        <span className="block font-mono font-semibold">{data.code}</span>
        <span className="block truncate text-[10px] text-muted">{data.name}</span>
      </span>
      <span
        aria-label={data.status ? STATUS[data.status].label : CONDITION[data.condition].label}
        className="size-1.5 shrink-0 rounded-full"
        style={{ background: data.status ? STATUS[data.status].color : CONDITION[data.condition].color }}
      />
      <Handle type="source" position={Position.Right} className="!size-1 !min-h-0 !min-w-0 !border-0 !bg-transparent" />
    </div>
  );
});

const nodeTypes = { asset: AssetNodeView };

interface Props {
  graph: Schemas["GraphResult"];
  highlight: Highlight;
  showAccess: boolean;
  onSelect: (code: string | null) => void;
  statuses?: ReadonlyMap<string, FunctionalStatus> | null;
}

function GraphCanvas({ graph, highlight, showAccess, onSelect, statuses = null }: Props) {
  const [positions, setPositions] = useState<Map<string, { x: number; y: number }> | null>(null);
  const [layoutError, setLayoutError] = useState<string | null>(null);
  const { fitView } = useReactFlow();

  useEffect(() => {
    let cancelled = false;
    layoutGraph(graph.nodes, graph.edges, showAccess)
      .then((p) => !cancelled && setPositions(p))
      .catch((e: unknown) => !cancelled && setLayoutError(String(e)));
    return () => {
      cancelled = true;
    };
  }, [graph, showAccess]);

  const nodes: AssetNode[] = useMemo(
    () =>
      positions
        ? graph.nodes.map((n) => ({
            id: n.code,
            type: "asset" as const,
            position: positions.get(n.code) ?? { x: 0, y: 0 },
            data: {
              code: n.code,
              name: n.name,
              category: n.category,
              condition: n.condition,
              role: roleOf(n.code, highlight),
              status: statuses?.get(n.code) ?? null,
            },
            ariaLabel: `${n.code} ${n.name}`,
            selected: n.code === highlight.selected,
          }))
        : [],
    [graph.nodes, positions, highlight, statuses],
  );

  const edges: Edge[] = useMemo(
    () =>
      graph.edges
        .filter((e) => showAccess || !isAccessEdge(e))
        .map((e) => {
          const inChain = edgeIsInChain(e, highlight);
          const faded = highlight.selected !== null && !inChain;
          const hidden =
            roleOf(e.provider, highlight) === "hidden" || roleOf(e.dependent, highlight) === "hidden";
          const upstreamSide = e.dependent === highlight.selected || highlight.upstream.has(e.dependent);
          return {
            id: `${e.provider}->${e.dependent}:${e.service_type}`,
            source: e.provider,
            target: e.dependent,
            selectable: false,
            style: {
              stroke: inChain ? (upstreamSide ? UPSTREAM_COLOR : DOWNSTREAM_COLOR) : "#36414f",
              strokeWidth: inChain ? 1.6 : 1,
              strokeDasharray: e.mode === "SOFT" ? "4 3" : undefined,
              opacity: hidden ? 0.03 : faded ? 0.12 : 0.9,
            },
          };
        }),
    [graph.edges, highlight, showAccess],
  );

  // Bring the selection's chain into view.
  useEffect(() => {
    if (!positions || !highlight.selected) return;
    const ids = [highlight.selected, ...highlight.upstream, ...highlight.downstream].map((id) => ({ id }));
    const t = setTimeout(() => fitView({ nodes: ids, duration: 400, maxZoom: 1.2, padding: 0.15 }), 30);
    return () => clearTimeout(t);
  }, [positions, highlight, fitView]);

  if (layoutError) {
    return <div className="p-4 text-crit">Graph layout failed: {layoutError}</div>;
  }
  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={(_, node) => onSelect(node.id)}
      onPaneClick={() => onSelect(null)}
      nodesDraggable={false}
      nodesConnectable={false}
      edgesFocusable={false}
      fitView
      minZoom={0.15}
      maxZoom={2}
      proOptions={{ hideAttribution: true }}
      colorMode="dark"
    >
      <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#1b232d" />
      <Controls showInteractive={false} position="top-right" />
    </ReactFlow>
  );
}

export default function DependencyGraph(props: Props) {
  return (
    <div className="h-full w-full" data-testid="twin-graph">
      <ReactFlowProvider>
        <GraphCanvas {...props} />
      </ReactFlowProvider>
    </div>
  );
}
