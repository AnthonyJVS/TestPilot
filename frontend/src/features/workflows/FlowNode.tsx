import { Handle, Position, type NodeProps } from "@xyflow/react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { memo } from "react";

import { cn } from "@/lib/utils";

import type { FlowNode as FlowNodeType } from "./graph";
import { CATEGORY } from "./node-meta";

const RUN_STYLES: Record<string, string> = {
  waiting: "",
  running: "border-beacon ring-2 ring-beacon/40",
  completed: "border-completed",
  failed: "border-failed ring-2 ring-failed/30",
  skipped: "border-dashed opacity-55",
  cancelled: "border-cancelled opacity-70",
};

const RUN_LABEL: Record<string, string> = {
  waiting: "Waiting",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  skipped: "Skipped",
  cancelled: "Cancelled",
};

function FlowNodeView({ data, selected }: NodeProps<FlowNodeType>) {
  const def = data.def;
  const category = CATEGORY[def?.category ?? "logic"] ?? CATEGORY.logic!;
  const Icon = category.icon;
  const errors = data.issues?.filter((i) => i.severity === "error").length ?? 0;
  const run = data.run;
  return (
    <div
      className={cn(
        "w-60 rounded-panel border border-border-strong bg-panel text-left shadow-lg shadow-black/20 transition-colors",
        selected && "border-beacon",
        errors > 0 && !run && "border-failed",
        run && RUN_STYLES[run.status],
      )}
    >
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <Icon className={cn("size-4 shrink-0", category.tone)} aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-semibold">{data.label || def?.label || data.type}</p>
          <p className="truncate font-mono text-[10px] text-faint">{data.type}</p>
        </div>
        {errors > 0 && !run ? (
          <span title={data.issues?.map((i) => i.message).join("\n")} className="text-failed">
            <AlertTriangle className="size-4" aria-label={`${errors} problems`} />
          </span>
        ) : null}
        {run?.status === "running" ? <Loader2 className="size-4 animate-spin text-beacon" aria-label="Running" /> : null}
      </div>
      <div className="grid grid-cols-2 gap-x-2 py-1.5 text-[11px]">
        <div className="space-y-1">
          {def?.inputs.map((port) => (
            <div key={port.name} className="relative pl-3 text-muted">
              <Handle
                type="target"
                position={Position.Left}
                id={port.name}
                className="!size-2.5 !border-2 !border-panel !bg-border-strong"
                style={{ left: -6 }}
              />
              {port.label}
              {port.required ? "" : " ?"}
            </div>
          ))}
        </div>
        <div className="space-y-1">
          {def?.outputs.map((port) => (
            <div key={port.name} className={cn("relative pr-3 text-right", port.name === "error" ? "text-failed" : "text-muted")}>
              {port.label}
              <Handle
                type="source"
                position={Position.Right}
                id={port.name}
                className={cn("!size-2.5 !border-2 !border-panel", port.name === "error" ? "!bg-failed" : "!bg-beacon")}
                style={{ right: -6 }}
              />
            </div>
          ))}
        </div>
      </div>
      {run && run.status !== "waiting" ? (
        <div className="border-t border-border px-3 py-1.5 text-[11px]">
          <span className={cn(run.status === "failed" ? "text-failed" : run.status === "completed" ? "text-completed" : "text-faint")}>
            {RUN_LABEL[run.status]}
          </span>
          {run.duration_ms !== null ? <span className="ml-2 font-mono text-faint">{(run.duration_ms / 1000).toFixed(1)}s</span> : null}
          {run.attempts > 1 ? <span className="ml-2 text-warning">{run.attempts} attempts</span> : null}
          {run.summary ? <p className="truncate text-faint">{run.summary}</p> : null}
        </div>
      ) : null}
    </div>
  );
}

export const FlowNode = memo(FlowNodeView);
