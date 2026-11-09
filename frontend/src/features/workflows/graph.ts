/** Conversion between the backend graph document and XYFlow nodes/edges, plus port rules. */
import type { Edge, Node } from "@xyflow/react";

import type { GraphIssue, GraphNode, NodeExecution, NodeTypeDef, RetryPolicy, WorkflowGraph } from "@/types/api";

export interface FlowNodeData extends Record<string, unknown> {
  type: string;
  label: string;
  config: Record<string, unknown>;
  retry: RetryPolicy;
  timeout_seconds: number | null;
  def?: NodeTypeDef;
  issues?: GraphIssue[];
  run?: NodeExecution;
}

export type FlowNode = Node<FlowNodeData, "flow">;

export const DEFAULT_RETRY: RetryPolicy = {
  max_attempts: 1,
  backoff: "exponential",
  base_seconds: 1,
  max_seconds: 30,
  retry_on: "transient",
};

/** Mirrors app/services/workflows/registry.py::compatible. */
export function compatible(source: string, target: string): boolean {
  if (source === target || target === "any") return true;
  if (source === "any") return target === "json" || target === "text";
  return target === "json" && ["analysis", "result", "test_plan", "error"].includes(source);
}

export function edgeStyle(sourceHandle: string | null | undefined): Partial<Edge> {
  return sourceHandle === "error"
    ? { style: { stroke: "var(--status-failed)", strokeDasharray: "6 4" }, animated: false }
    : { style: { stroke: "var(--border-strong)", strokeWidth: 1.5 } };
}

export function toFlow(
  graph: WorkflowGraph,
  defs: Map<string, NodeTypeDef>,
  extra: { issues?: GraphIssue[]; runs?: Map<string, NodeExecution> } = {},
): { nodes: FlowNode[]; edges: Edge[] } {
  return {
    nodes: (graph.nodes ?? []).map((n) => ({
      id: n.id,
      type: "flow",
      position: { x: n.position?.x ?? 0, y: n.position?.y ?? 0 },
      data: {
        type: n.type,
        label: n.label,
        config: n.config ?? {},
        retry: n.retry ?? DEFAULT_RETRY,
        timeout_seconds: n.timeout_seconds ?? null,
        def: defs.get(n.type),
        issues: extra.issues?.filter((i) => i.node_id === n.id),
        run: extra.runs?.get(n.id),
      },
    })),
    edges: (graph.edges ?? []).map((e) => ({
      id: e.id,
      source: e.source,
      sourceHandle: e.source_handle,
      target: e.target,
      targetHandle: e.target_handle,
      ...edgeStyle(e.source_handle),
    })),
  };
}

export function fromFlow(nodes: FlowNode[], edges: Edge[]): WorkflowGraph {
  return {
    nodes: nodes.map(
      (n): GraphNode => ({
        id: n.id,
        type: n.data.type,
        label: n.data.label,
        position: { x: Math.round(n.position.x), y: Math.round(n.position.y) },
        config: n.data.config,
        retry: n.data.retry,
        timeout_seconds: n.data.timeout_seconds,
      }),
    ),
    edges: edges.map((e) => ({
      id: e.id,
      source: e.source,
      source_handle: e.sourceHandle ?? "",
      target: e.target,
      target_handle: e.targetHandle ?? "",
    })),
  };
}

export function newNodeId(type: string, existing: Set<string>): string {
  const base = type.split(".").pop()?.replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 30) || "node";
  let n = 1;
  while (existing.has(`${base}_${n}`)) n += 1;
  return `${base}_${n}`;
}

export function newEdgeId(): string {
  return `e_${Math.random().toString(36).slice(2, 10)}`;
}

/** Stable comparison of graphs (positions rounded, key order normalised by JSON round-trip). */
export function sameGraph(a: WorkflowGraph, b: WorkflowGraph): boolean {
  const norm = (g: WorkflowGraph) =>
    JSON.stringify({
      nodes: (g.nodes ?? []).map((n) => ({ ...n, position: { x: Math.round(n.position?.x ?? 0), y: Math.round(n.position?.y ?? 0) } })),
      edges: g.edges ?? [],
    });
  return norm(a) === norm(b);
}
