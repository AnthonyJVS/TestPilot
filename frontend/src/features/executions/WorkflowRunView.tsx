import "@xyflow/react/dist/style.css";

import { Background, Controls, ReactFlow, ReactFlowProvider } from "@xyflow/react";
import { X } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { useNodeTypes } from "@/features/workflows/api";
import { nodeTypes } from "@/features/workflows/flow-types";
import { toFlow } from "@/features/workflows/graph";
import { cn } from "@/lib/utils";
import { useThemeStore } from "@/stores/theme-store";
import type { Execution, ExecutionEvent, NodeExecution, WorkflowRun } from "@/types/api";

import { TERMINAL, type StreamState } from "./api";
import { RunHeader } from "./ExecutionPage";
import { formatMs } from "./format";
import { AIRequestDetails, ArtifactsSection, Evidence, Filmstrip, Preview, ReplayBar, Timeline } from "./parts";
import { frameAt, framesOf, nodeStatesAt, useReplay } from "./replay";

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
  const defs = useNodeTypes();
  const theme = useThemeStore((s) => s.theme);
  const replay = useReplay(events);
  const frames = useMemo(() => framesOf(events), [events]);
  const [selected, setSelected] = useState<string | null>(null);

  // While replaying, node states are re-derived from the event log at the cursor.
  const nodes = useMemo(() => {
    if (!replay.replaying) return workflow.nodes;
    const states = nodeStatesAt(events, replay.at);
    return workflow.nodes.map((n): NodeExecution => {
      const status = states.get(n.node_id) ?? "waiting";
      const final = status === n.status;
      return { ...n, status, summary: final ? n.summary : null, duration_ms: final ? n.duration_ms : null };
    });
  }, [workflow.nodes, events, replay.replaying, replay.at]);
  const runs = useMemo(() => new Map(nodes.map((n) => [n.node_id, n])), [nodes]);
  const flow = useMemo(() => {
    if (!workflow.graph || !defs.data) return null;
    return toFlow(workflow.graph, new Map(defs.data.map((d) => [d.type, d])), { runs });
  }, [workflow.graph, defs.data, runs]);

  const frame = frameAt(frames, replay.at, { nodeId: selected });
  const done = nodes.filter((n) => !["waiting", "running"].includes(n.status)).length;
  const progress = nodes.length ? (done / nodes.length) * 100 : 0;
  const current = selected ? runs.get(selected) : undefined;
  const running = live && !replay.replaying;

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <RunHeader
        execution={execution}
        title={workflow.workflow_name}
        version={workflow.version}
        back={workflow.workflow_id ? { to: `/workflows/${workflow.workflow_id}`, label: workflow.workflow_name } : null}
        streamState={streamState}
        progress={progress}
        meta={
          <span>
            {done}/{nodes.length} nodes finished
          </span>
        }
      />
      <ReplayBar replay={replay} events={events} live={live} />

      <section aria-label="Workflow canvas" className="h-[380px] overflow-hidden rounded-panel border border-border bg-sunken">
        {flow ? (
          <ReactFlowProvider>
            <ReactFlow
              nodes={flow.nodes.map((n) => ({ ...n, selected: n.id === selected }))}
              edges={flow.edges.map((e) => {
                const source = runs.get(e.source);
                const flowing = source?.status === "completed" && e.sourceHandle !== "error";
                return { ...e, animated: running && flowing };
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
            {nodes.map((node) => (
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
          {current ? (
            <NodeInspector key={current.node_id} node={workflow.nodes.find((n) => n.node_id === current.node_id) ?? current} events={events.filter((e) => e.node_id === current.node_id)} onClose={() => setSelected(null)} />
          ) : (
            <p className="text-xs text-faint">Select a node on the canvas or in the list to inspect it.</p>
          )}
        </section>
        <section aria-labelledby="preview-heading" className="space-y-3">
          <h2 id="preview-heading" className="text-[15px] font-semibold [font-stretch:100%]">
            Browser preview {selected ? <span className="font-normal text-faint">· {runs.get(selected)?.label}</span> : null}
          </h2>
          <Preview
            frame={frame}
            caption={frame ? `${frame.interim ? "During" : "After"} ${runs.get(frame.nodeId ?? "")?.label ?? frame.nodeId}` : null}
            live={live}
            startTs={events[0]?.ts}
          />
          <Filmstrip frames={frames} at={replay.at} onSeek={replay.seek} label={(f) => runs.get(f.nodeId ?? "")?.label ?? "Frame"} />
        </section>
      </div>

      <Timeline events={selected ? events.filter((e) => e.node_id === selected || e.category === "system") : events} at={replay.at} replaying={replay.replaying} onSeek={replay.seek} />
      <ArtifactsSection execution={execution} live={live} />
    </div>
  );
}

const TABS = ["Overview", "Evidence", "AI"] as const;

function NodeInspector({ node, events, onClose }: { node: NodeExecution; events: ExecutionEvent[]; onClose: () => void }) {
  const aiRequests = events.filter((e) => e.type === "ai.request.completed" && typeof e.data.ai_request_id === "string").map((e) => String(e.data.ai_request_id));
  const tabs = TABS.filter((t) => t !== "AI" || aiRequests.length > 0 || node.node_type.startsWith("ai."));
  const [tab, setTab] = useState<(typeof TABS)[number]>(aiRequests.length ? "AI" : "Overview");
  return (
    <div className="space-y-3 rounded-panel border border-border bg-panel p-4 text-[13px]" aria-label={`${node.label} details`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-medium">{node.label}</p>
          <p className="font-mono text-[11px] text-faint">
            {node.node_type} · {node.node_id}
          </p>
        </div>
        <Button variant="ghost" size="icon" className="size-7" aria-label="Close node details" onClick={onClose}>
          <X />
        </Button>
      </div>
      <div role="tablist" aria-label="Node details" className="flex gap-1 border-b border-border">
        {tabs.map((name) => (
          <button
            key={name}
            role="tab"
            type="button"
            aria-selected={tab === name}
            onClick={() => setTab(name)}
            className={cn("-mb-px border-b-2 px-2.5 py-1.5 text-xs", tab === name ? "border-beacon text-text" : "border-transparent text-muted hover:text-text")}
          >
            {name}
            {name === "AI" && aiRequests.length ? ` (${aiRequests.length})` : ""}
          </button>
        ))}
      </div>
      {tab === "Overview" ? (
        <div className="space-y-2">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
            <dt className="text-faint">Status</dt>
            <dd className={cn("capitalize", NODE_TONE[node.status])}>{node.status}</dd>
            <dt className="text-faint">Attempts</dt>
            <dd>{node.attempts}</dd>
            <dt className="text-faint">Duration</dt>
            <dd>{formatMs(node.duration_ms)}</dd>
            {node.summary ? (
              <>
                <dt className="text-faint">Summary</dt>
                <dd>{node.summary}</dd>
              </>
            ) : null}
          </dl>
          {node.error_message ? (
            <pre className="max-h-48 overflow-auto rounded-control border border-failed/30 bg-failed/5 p-2.5 font-mono text-[12px] whitespace-pre-wrap text-failed">
              {node.error_code}: {node.error_message}
            </pre>
          ) : null}
          {node.output ? (
            <>
              <p className="text-xs font-medium text-muted">Output (secrets removed)</p>
              <pre className="max-h-64 overflow-auto rounded-control border border-border bg-sunken p-2.5 font-mono text-[12px] leading-5 whitespace-pre-wrap break-words text-muted">
                {JSON.stringify(node.output, null, 2)}
              </pre>
            </>
          ) : null}
        </div>
      ) : null}
      {tab === "Evidence" ? (
        <div className="space-y-2">
          <p className="text-xs text-faint">
            {events.filter((e) => e.type.startsWith("browser.step")).length} browser actions ·{" "}
            {events.filter((e) => e.type === "browser.frame").length} screenshots and frames
          </p>
          <Evidence events={events} />
        </div>
      ) : null}
      {tab === "AI" ? (
        <div className="space-y-2">
          {aiRequests.length ? aiRequests.map((id) => <AIRequestDetails key={id} id={id} />) : <p className="text-xs text-faint">No AI call was made by this node yet.</p>}
        </div>
      ) : null}
    </div>
  );
}
