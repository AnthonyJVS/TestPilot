import "@xyflow/react/dist/style.css";

import {
  addEdge,
  Background,
  type Connection,
  Controls,
  type Edge,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from "@xyflow/react";
import { AlertTriangle, CheckCircle2, Copy, Loader2, Play, Save, Search, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";

import { ErrorState } from "@/components/common/ErrorState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import { useThemeStore } from "@/stores/theme-store";
import type { GraphIssue, NodeTypeDef, Workflow } from "@/types/api";

import { useDuplicateWorkflow, useNodeTypes, useRenameWorkflow, useRunWorkflow, useSaveVersion, useWorkflow, validateGraph } from "./api";
import { nodeTypes } from "./flow-types";
import { compatible, DEFAULT_RETRY, edgeStyle, type FlowNode, fromFlow, newEdgeId, newNodeId, sameGraph, toFlow } from "./graph";
import { CATEGORY } from "./node-meta";
import { type JsonSchema, SchemaForm } from "./SchemaForm";

const DRAG_TYPE = "application/testpilot-node";

export function StudioPage() {
  const { workflowId = "" } = useParams();
  const workflow = useWorkflow(workflowId);
  const defs = useNodeTypes();
  if (workflow.isPending || defs.isPending) return <Skeleton className="h-[70vh] rounded-panel" />;
  if (workflow.error || defs.error) {
    return (
      <div className="mx-auto max-w-3xl">
        <ErrorState error={workflow.error ?? defs.error} title="This workflow could not be opened" onRetry={() => void workflow.refetch()} />
      </div>
    );
  }
  return (
    <ReactFlowProvider>
      <Studio key={workflow.data.id} workflow={workflow.data} defs={defs.data} />
    </ReactFlowProvider>
  );
}

function Studio({ workflow, defs }: { workflow: Workflow; defs: NodeTypeDef[] }) {
  const navigate = useNavigate();
  const theme = useThemeStore((s) => s.theme);
  const defMap = useMemo(() => new Map(defs.map((d) => [d.type, d])), [defs]);
  const initial = useMemo(() => toFlow(workflow.latest.graph, defMap, { issues: workflow.latest.issues }), [workflow.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(initial.edges);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [issues, setIssues] = useState<GraphIssue[]>(workflow.latest.issues);
  const [checking, setChecking] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null);
  const flow = useReactFlow();
  const save = useSaveVersion(workflow.id);
  const run = useRunWorkflow(workflow.id);
  const duplicate = useDuplicateWorkflow();

  const graph = useMemo(() => fromFlow(nodes, edges), [nodes, edges]);
  const graphKey = JSON.stringify(graph);
  const dirty = !sameGraph(graph, workflow.latest.graph);
  const errors = issues.filter((i) => i.severity === "error");

  // Live validation (debounced): the canvas highlights problems before saving.
  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setChecking(true);
      validateGraph(workflow.id, JSON.parse(graphKey), controller.signal)
        .then((result) => {
          setIssues(result.issues);
          setNodes((current) => current.map((n) => ({ ...n, data: { ...n.data, issues: result.issues.filter((i) => i.node_id === n.id) } })));
        })
        .catch(() => undefined)
        .finally(() => setChecking(false));
    }, 500);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [graphKey, workflow.id, setNodes]);

  const addNode = useCallback(
    (type: string, position?: { x: number; y: number }) => {
      const def = defMap.get(type);
      if (!def?.available) return;
      let at = position;
      if (!at) {
        const rect = wrapper.current?.getBoundingClientRect();
        at = flow.screenToFlowPosition({ x: (rect?.left ?? 0) + (rect?.width ?? 600) / 2, y: (rect?.top ?? 0) + (rect?.height ?? 400) / 2 });
      }
      setNodes((current) => {
        const id = newNodeId(type, new Set(current.map((n) => n.id)));
        setSelectedId(id);
        return [
          ...current.map((n) => ({ ...n, selected: false })),
          {
            id,
            type: "flow",
            position: at,
            selected: true,
            data: { type, label: def.label, config: structuredClone(def.defaults), retry: { ...DEFAULT_RETRY }, timeout_seconds: null, def },
          },
        ];
      });
    },
    [defMap, flow, setNodes],
  );

  const isValidConnection = useCallback(
    (connection: Connection | Edge) => {
      if (connection.source === connection.target) return false;
      const source = nodes.find((n) => n.id === connection.source)?.data.def;
      const target = nodes.find((n) => n.id === connection.target)?.data.def;
      const out = source?.outputs.find((p) => p.name === connection.sourceHandle);
      const input = target?.inputs.find((p) => p.name === connection.targetHandle);
      if (!out || !input || !compatible(out.type, input.type)) return false;
      return input.multi || !edges.some((e) => e.target === connection.target && e.targetHandle === connection.targetHandle);
    },
    [nodes, edges],
  );

  const onConnect = useCallback(
    (connection: Connection) => setEdges((current) => addEdge({ ...connection, id: newEdgeId(), ...edgeStyle(connection.sourceHandle) }, current)),
    [setEdges],
  );

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    const type = event.dataTransfer.getData(DRAG_TYPE);
    if (type) addNode(type, flow.screenToFlowPosition({ x: event.clientX, y: event.clientY }));
  };

  const updateNode = (id: string, patch: Partial<FlowNode["data"]>) =>
    setNodes((current) => current.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)));
  const removeNode = (id: string) => {
    setNodes((current) => current.filter((n) => n.id !== id));
    setEdges((current) => current.filter((e) => e.source !== id && e.target !== id));
    setSelectedId(null);
  };

  const onSave = () =>
    save.mutate(graph, {
      onSuccess: (saved) => toast.success(dirty ? `Saved as version ${saved.latest.version}` : "No changes to save"),
      onError: (error) => toast.error(error.message),
    });

  const onRun = async () => {
    try {
      if (dirty) await save.mutateAsync(graph);
      const execution = await run.mutateAsync();
      toast.success("Workflow started");
      void navigate(`/executions/${execution.id}`);
    } catch (error) {
      if (error instanceof ApiError) {
        const found = (error.details as { issues?: GraphIssue[] } | null)?.issues;
        if (found) setIssues(found);
      }
      toast.error(error instanceof Error ? error.message : "The workflow could not start.");
    }
  };

  const selected = nodes.find((n) => n.id === selectedId) ?? null;

  return (
    <div className="flex flex-col gap-3 xl:h-[calc(100dvh-7.5rem)] xl:min-h-[560px]">
      <StudioHeader workflow={workflow} dirty={dirty} />
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("inline-flex items-center gap-1.5 text-[13px]", errors.length ? "text-failed" : "text-completed")}>
          {checking ? <Loader2 className="size-4 animate-spin text-faint" /> : errors.length ? <AlertTriangle className="size-4" /> : <CheckCircle2 className="size-4" />}
          {errors.length ? `${errors.length} problem${errors.length > 1 ? "s" : ""} to fix` : "Ready to run"}
        </span>
        <span className="text-[13px] text-faint">
          · v{workflow.latest.version}
          {dirty ? " · unsaved changes" : " · saved"}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              duplicate.mutate(workflow.id, {
                onSuccess: (copy) => {
                  toast.success(`Created ${copy.name}`);
                  void navigate(`/workflows/${copy.id}`);
                },
              })
            }
          >
            <Copy /> Duplicate
          </Button>
          <Button variant="secondary" size="sm" onClick={onSave} disabled={save.isPending || !dirty}>
            {save.isPending ? <Loader2 className="animate-spin" /> : <Save />} Save version
          </Button>
          <Button size="sm" onClick={() => void onRun()} disabled={run.isPending || save.isPending || errors.length > 0 || nodes.length === 0}>
            {run.isPending ? <Loader2 className="animate-spin" /> : <Play />} Run
          </Button>
        </div>
      </div>

      <div className="grid gap-3 xl:min-h-0 xl:flex-1 xl:grid-cols-[13rem_minmax(0,1fr)_19rem]">
        <Palette defs={defs} onAdd={(type) => addNode(type)} />
        <div ref={wrapper} className="relative order-1 h-[62vh] min-h-[420px] overflow-hidden rounded-panel border border-border bg-sunken xl:order-2 xl:h-auto" onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            isValidConnection={isValidConnection}
            onSelectionChange={({ nodes: picked }) => setSelectedId(picked.length === 1 ? (picked[0]?.id ?? null) : null)}
            colorMode={theme}
            fitView
            fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
            deleteKeyCode={["Backspace", "Delete"]}
            proOptions={{ hideAttribution: true }}
            style={{ backgroundColor: "transparent" }}
          >
            <Background gap={20} size={1} />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable className="!bg-panel" maskColor="rgba(0,0,0,0.25)" />
          </ReactFlow>
          {nodes.length === 0 ? (
            <p className="pointer-events-none absolute inset-0 flex items-center justify-center text-[13px] text-faint">Drag nodes from the palette, or click one to add it.</p>
          ) : null}
        </div>
        <aside className="order-3 max-h-[32rem] min-h-0 overflow-y-auto rounded-panel border border-border bg-panel p-4 xl:max-h-none" aria-label="Inspector">
          {selected ? (
            <NodeInspector key={selected.id} node={selected} projectId={workflow.project_id} onChange={(patch) => updateNode(selected.id, patch)} onRemove={() => removeNode(selected.id)} />
          ) : (
            <IssuesPanel
              issues={issues}
              nodes={nodes}
              onSelect={(id) => {
                setSelectedId(id);
                setNodes((current) => current.map((n) => ({ ...n, selected: n.id === id })));
              }}
            />
          )}
        </aside>
      </div>
    </div>
  );
}

function StudioHeader({ workflow, dirty }: { workflow: Workflow; dirty: boolean }) {
  const rename = useRenameWorkflow(workflow.id);
  const [name, setName] = useState(workflow.name);
  return (
    <header>
      <p className="text-[13px] text-faint">
        <Link to="/workflows" className="hover:text-text">
          Workflow Studio
        </Link>
      </p>
      <input
        aria-label="Workflow name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onBlur={() => {
          if (name.trim() && name !== workflow.name) rename.mutate({ name }, { onError: (e) => toast.error(e.message) });
        }}
        className="-ml-1 w-full max-w-xl rounded-control bg-transparent px-1 text-[24px] font-semibold focus-visible:bg-sunken focus-visible:outline-none"
      />
      {dirty ? <span className="sr-only">Unsaved changes</span> : null}
    </header>
  );
}

function Palette({ defs, onAdd }: { defs: NodeTypeDef[]; onAdd: (type: string) => void }) {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const shown = defs.filter((d) => !q || d.label.toLowerCase().includes(q) || d.description.toLowerCase().includes(q) || d.type.includes(q));
  return (
    <aside className="order-2 flex max-h-80 min-h-0 flex-col rounded-panel border border-border bg-panel xl:order-1 xl:max-h-none" aria-label="Node palette">
      <div className="relative border-b border-border p-2">
        <Search className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-faint" aria-hidden />
        <Input aria-label="Search nodes" placeholder="Search nodes" value={query} onChange={(e) => setQuery(e.target.value)} className="h-9 pl-8" />
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-2">
        {Object.entries(CATEGORY).map(([key, meta]) => {
          const items = shown.filter((d) => d.category === key);
          if (!items.length) return null;
          const Icon = meta.icon;
          return (
            <section key={key}>
              <h3 className="mb-1 flex items-center gap-1.5 px-1 text-[11px] font-semibold tracking-wide text-faint uppercase">
                <Icon className={cn("size-3.5", meta.tone)} aria-hidden /> {meta.label}
              </h3>
              <ul className="space-y-0.5">
                {items.map((def) => (
                  <li key={def.type}>
                    <button
                      type="button"
                      draggable={def.available}
                      disabled={!def.available}
                      onDragStart={(e) => {
                        e.dataTransfer.setData(DRAG_TYPE, def.type);
                        e.dataTransfer.effectAllowed = "move";
                      }}
                      onClick={() => onAdd(def.type)}
                      title={def.available ? def.description : def.milestone ? `Planned for milestone ${def.milestone}` : "Planned after v1"}
                      className="w-full rounded-control px-2 py-1.5 text-left text-[13px] hover:bg-raised disabled:cursor-not-allowed disabled:opacity-45"
                    >
                      {def.label}
                      {!def.available ? <span className="ml-1 text-[10px] text-faint">{def.milestone ? `M${def.milestone}` : "planned"}</span> : null}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </aside>
  );
}

function NodeInspector({
  node,
  projectId,
  onChange,
  onRemove,
}: {
  node: FlowNode;
  projectId: string;
  onChange: (patch: Partial<FlowNode["data"]>) => void;
  onRemove: () => void;
}) {
  const def = node.data.def;
  const retry = node.data.retry;
  const nodeIssues = node.data.issues ?? [];
  return (
    <div className="space-y-5">
      <div>
        <p className="font-mono text-[11px] text-faint">
          {node.data.type} · {node.id}
        </p>
        <p className="mt-1 text-[13px] text-muted">{def?.description}</p>
      </div>
      {nodeIssues.length ? (
        <ul className="space-y-1">
          {nodeIssues.map((issue) => (
            <li key={issue.code + issue.message} className={cn("text-[13px]", issue.severity === "error" ? "text-failed" : "text-warning")}>
              {issue.message}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="space-y-1.5">
        <Label htmlFor="node-label">Label</Label>
        <Input id="node-label" value={node.data.label} maxLength={80} onChange={(e) => onChange({ label: e.target.value })} />
      </div>
      {def ? (
        <SchemaForm
          schema={def.config_schema as JsonSchema}
          value={node.data.config}
          onChange={(config) => onChange({ config })}
          projectId={projectId}
          idPrefix={`cfg-${node.id}`}
        />
      ) : null}
      <details className="rounded-control border border-border px-3 py-2">
        <summary className="cursor-pointer text-[13px] font-medium">Retry and timeout</summary>
        <div className="mt-3 grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="retry-attempts">Attempts</Label>
            <Input
              id="retry-attempts"
              type="number"
              min={1}
              max={5}
              value={retry.max_attempts}
              onChange={(e) => onChange({ retry: { ...retry, max_attempts: Math.min(5, Math.max(1, Number(e.target.value) || 1)) } })}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="retry-delay">First delay (s)</Label>
            <Input id="retry-delay" type="number" min={0} max={60} value={retry.base_seconds} onChange={(e) => onChange({ retry: { ...retry, base_seconds: Math.max(0, Number(e.target.value) || 0) } })} />
          </div>
          <div className="col-span-2 space-y-1.5">
            <Label htmlFor="retry-on">Retry on</Label>
            <NativeSelect id="retry-on" value={retry.retry_on} onChange={(e) => onChange({ retry: { ...retry, retry_on: e.target.value as typeof retry.retry_on } })}>
              <option value="transient">Temporary errors (timeouts, rate limits)</option>
              <option value="any">Any error</option>
            </NativeSelect>
          </div>
          <div className="col-span-2 space-y-1.5">
            <Label htmlFor="node-timeout">Timeout per attempt (s)</Label>
            <Input
              id="node-timeout"
              type="number"
              min={1}
              max={900}
              placeholder="Run limit"
              value={node.data.timeout_seconds ?? ""}
              onChange={(e) => onChange({ timeout_seconds: e.target.value ? Math.min(900, Math.max(1, Number(e.target.value))) : null })}
            />
          </div>
        </div>
      </details>
      <Button variant="ghost" size="sm" onClick={onRemove} className="text-failed">
        <Trash2 /> Delete node
      </Button>
    </div>
  );
}

function IssuesPanel({ issues, nodes, onSelect }: { issues: GraphIssue[]; nodes: FlowNode[]; onSelect: (id: string) => void }) {
  const label = (id: string | null | undefined) => nodes.find((n) => n.id === id)?.data.label ?? id;
  return (
    <div className="space-y-3">
      <h2 className="text-[15px] font-semibold [font-stretch:100%]">Checks</h2>
      {issues.length === 0 ? (
        <p className="text-[13px] text-muted">No problems found. Select a node to edit its settings.</p>
      ) : (
        <ul className="space-y-2">
          {issues.map((issue, index) => (
            <li key={`${issue.code}-${issue.node_id ?? issue.edge_id ?? ""}-${index}`}>
              <button
                type="button"
                disabled={!issue.node_id}
                onClick={() => issue.node_id && onSelect(issue.node_id)}
                className="w-full rounded-control border border-border px-3 py-2 text-left text-[13px] hover:bg-raised disabled:cursor-default disabled:hover:bg-transparent"
              >
                <span className={issue.severity === "error" ? "text-failed" : "text-warning"}>{issue.severity === "error" ? "Error" : "Warning"}</span>
                {issue.node_id ? <span className="text-faint"> · {label(issue.node_id)}</span> : null}
                <span className="block text-muted">{issue.message}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-faint">
        Connect outputs to inputs of a matching type. Every node has an <span className="text-failed">On error</span> output: connect it to handle failures instead of
        stopping the run.
      </p>
    </div>
  );
}
