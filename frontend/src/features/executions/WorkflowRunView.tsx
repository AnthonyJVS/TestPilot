import "@xyflow/react/dist/style.css";

import { Background, Controls, ReactFlow, ReactFlowProvider } from "@xyflow/react";
import { AlertTriangle, Loader2, Square } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useNodeTypes } from "@/features/workflows/api";
import { nodeTypes } from "@/features/workflows/flow-types";
import { toFlow } from "@/features/workflows/graph";
import { cn, formatDateTime } from "@/lib/utils";
import { useThemeStore } from "@/stores/theme-store";
import type { Artifact, Execution, ExecutionEvent, NodeExecution, WorkflowRun } from "@/types/api";

import { TERMINAL, useCancelRun, type StreamState } from "./api";
import { ArtifactsSection, LiveBadge, Preview, Timeline } from "./ExecutionPage";
import { formatMs } from "./format";
import { RunStatus } from "./status";

const NODE_TONE: Record<NodeExecution["status"], string> = {
  waiting: "text-faint",
  running: "text-beacon",
  completed: "text-completed",
  failed: "text-failed",
  skipped: "text-faint",
  cancelled: "text-cancelled",
};

export function WorkflowRunView({
  execution,
  workflow,
  events,
  streamState,
}: {
  execution: Execution;
  workflow: WorkflowRun;
  events: ExecutionEvent[];
  streamState: StreamState;
}) {
  const live = !TERMINAL.has(execution.status);
  const cancel = useCancelRun(execution.id);
  const defs = useNodeTypes();
  const theme = useThemeStore((s) => s.theme);
  const [selected, setSelected] = useState<string | null>(null);

  const runs = useMemo(() => new Map(workflow.nodes.map((n) => [n.node_id, n])), [workflow.nodes]);
  const flow = useMemo(() => {
    if (!workflow.graph || !defs.data) return null;
    return toFlow(workflow.graph, new Map(defs.data.map((d) => [d.type, d])), { runs });
  }, [workflow.graph, defs.data, runs]);

  const frames = useMemo(() => execution.artifacts.filter((a) => a.kind === "screenshot" && a.content_type === "image/jpeg"), [execution.artifacts]);
  const frameEvents = useMemo(() => new Map(events.filter((e) => e.type === "browser.frame").map((e) => [String(e.data.artifact_id), e])), [events]);
  const nodeFrames = selected ? frames.filter((a) => a.node_id === selected) : frames;
  const frame: Artifact | undefined = nodeFrames[nodeFrames.length - 1];
  const frameEvent = frame ? frameEvents.get(frame.id) : undefined;
  const done = workflow.nodes.filter((n) => !["waiting", "running"].includes(n.status)).length;
  const progress = workflow.nodes.length ? (done / workflow.nodes.length) * 100 : 0;
  const current = selected ? runs.get(selected) : undefined;

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <header className="space-y-3">
        <p className="text-[13px] text-faint">
          <Link to="/executions" className="hover:text-text">
            Executions
          </Link>
          {workflow.workflow_id ? (
            <>
              {" / "}
              <Link to={`/workflows/${workflow.workflow_id}`} className="hover:text-text">
                {workflow.workflow_name}
              </Link>
            </>
          ) : null}
        </p>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-[26px] font-semibold">
              {workflow.workflow_name} <span className="font-normal text-faint">v{workflow.version}</span>
            </h1>
            <RunStatus status={execution.status} className="text-sm" />
          </div>
          <div className="flex items-center gap-2">
            <LiveBadge state={streamState} live={live} />
            {live ? (
              <Button
                variant="secondary"
                size="sm"
                disabled={execution.cancel_requested || cancel.isPending}
                onClick={() => cancel.mutate(undefined, { onSuccess: () => toast("Cancelling the run…") })}
              >
                {cancel.isPending ? <Loader2 className="animate-spin" /> : <Square />}
                {execution.cancel_requested ? "Cancelling…" : "Cancel run"}
              </Button>
            ) : null}
          </div>
        </div>
        <p className="flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-muted">
          <span>
            {done}/{workflow.nodes.length} nodes finished
          </span>
          <span>{execution.started_at ? formatDateTime(execution.started_at) : `Queued ${formatDateTime(execution.created_at)}`}</span>
          <span className="font-mono">{formatMs(execution.duration_ms)}</span>
          <span className={execution.isolated ? "text-completed" : "text-warning"}>
            {execution.isolated ? "Isolated browser worker" : "Development mode (not isolated)"}
          </span>
        </p>
        <div className="h-1 overflow-hidden rounded-full bg-sunken" role="progressbar" aria-valuenow={Math.round(progress)} aria-valuemin={0} aria-valuemax={100} aria-label="Run progress">
          <div
            className={cn("h-full transition-[width] duration-500", execution.status === "passed" ? "bg-completed" : execution.status === "failed" || execution.status === "error" ? "bg-failed" : "bg-beacon")}
            style={{ width: `${progress}%` }}
          />
        </div>
        {execution.notes.map((note) => (
          <p key={note} className="flex gap-2 rounded-control border border-border bg-raised/50 px-3 py-2 text-[13px] text-muted">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden /> {note}
          </p>
        ))}
        {execution.error_message && execution.status !== "passed" ? (
          <p role="alert" className="rounded-control border border-failed/40 bg-failed/10 px-3 py-2 text-[13px] whitespace-pre-wrap text-failed">
            {execution.error_message}
          </p>
        ) : null}
      </header>

      <section aria-label="Workflow canvas" className="h-[380px] overflow-hidden rounded-panel border border-border bg-sunken">
        {flow ? (
          <ReactFlowProvider>
            <ReactFlow
              nodes={flow.nodes.map((n) => ({ ...n, selected: n.id === selected }))}
              edges={flow.edges.map((e) => {
                const source = runs.get(e.source);
                const flowing = source?.status === "completed" && !(e.sourceHandle === "error");
                return { ...e, animated: live && flowing };
              })}
              nodeTypes={nodeTypes}
              nodesDraggable={false}
              nodesConnectable={false}
              elementsSelectable
              onNodeClick={(_, node) => setSelected(node.id === selected ? null : node.id)}
              colorMode={theme}
              fitView
              fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
              proOptions={{ hideAttribution: true }}
              style={{ backgroundColor: "transparent" }}
            >
              <Background gap={20} size={1} />
              <Controls showInteractive={false} />
            </ReactFlow>
          </ReactFlowProvider>
        ) : (
          <div className="flex size-full items-center justify-center text-[13px] text-faint">Loading the canvas…</div>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        <section aria-labelledby="nodes-heading" className="space-y-3">
          <h2 id="nodes-heading" className="text-[15px] font-semibold [font-stretch:100%]">
            Nodes
          </h2>
          <ol className="divide-y divide-border overflow-hidden rounded-panel border border-border bg-panel">
            {workflow.nodes.map((node) => (
              <li key={node.node_id} className={cn(selected === node.node_id && "bg-raised/60")}>
                <button
                  type="button"
                  onClick={() => setSelected(node.node_id === selected ? null : node.node_id)}
                  className="grid w-full grid-cols-[1fr_auto] gap-x-3 px-4 py-2.5 text-left hover:bg-raised/40"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm">{node.label}</span>
                    <span className="block truncate font-mono text-xs text-faint">
                      {node.node_type}
                      {node.duration_ms !== null ? ` · ${formatMs(node.duration_ms)}` : ""}
                      {node.attempts > 1 ? ` · ${node.attempts} attempts` : ""}
                    </span>
                  </span>
                  <span className={cn("text-[13px] capitalize", NODE_TONE[node.status])}>{node.status}</span>
                </button>
              </li>
            ))}
          </ol>
          {current ? <NodeDetails node={current} /> : <p className="text-xs text-faint">Select a node on the canvas or in the list to inspect it.</p>}
        </section>
        <section aria-labelledby="preview-heading" className="space-y-3">
          <h2 id="preview-heading" className="text-[15px] font-semibold [font-stretch:100%]">
            Browser preview
          </h2>
          <Preview
            artifact={frame}
            url={typeof frameEvent?.data.url === "string" ? frameEvent.data.url : null}
            caption={frame ? `After ${runs.get(frame.node_id ?? "")?.label ?? frame.node_id}` : null}
            live={live}
          />
        </section>
      </div>

      <Timeline events={selected ? events.filter((e) => e.node_id === selected || e.category === "system") : events} />
      <ArtifactsSection execution={execution} live={live} />
    </div>
  );
}

function NodeDetails({ node }: { node: NodeExecution }) {
  return (
    <div className="space-y-2 rounded-panel border border-border bg-panel p-4 text-[13px]">
      <p className="font-medium">{node.label}</p>
      {node.summary ? <p className="text-muted">{node.summary}</p> : null}
      {node.error_message ? (
        <pre className="max-h-48 overflow-auto rounded-control border border-failed/30 bg-failed/5 p-2.5 font-mono text-[12px] whitespace-pre-wrap text-failed">
          {node.error_code}: {node.error_message}
        </pre>
      ) : null}
      {node.output ? (
        <>
          <p className="text-xs font-medium text-muted">Output</p>
          <pre className="max-h-64 overflow-auto rounded-control border border-border bg-sunken p-2.5 font-mono text-[12px] leading-5 whitespace-pre-wrap break-words text-muted">
            {JSON.stringify(node.output, null, 2)}
          </pre>
        </>
      ) : null}
    </div>
  );
}
