import { cn } from "@/lib/utils";

/**
 * Semantic states shared by system checks today and execution nodes later
 * (waiting, queued, running, completed, failed, skipped, cancelled).
 */
export type IndicatorState =
  | "ok"
  | "error"
  | "not_configured"
  | "waiting"
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "skipped"
  | "cancelled";

const STYLES: Record<IndicatorState, { dot: string; label: string }> = {
  ok: { dot: "bg-completed", label: "Operational" },
  error: { dot: "bg-failed", label: "Unavailable" },
  not_configured: { dot: "bg-waiting", label: "Not configured" },
  waiting: { dot: "bg-waiting", label: "Waiting" },
  queued: { dot: "bg-queued", label: "Queued" },
  running: { dot: "bg-running animate-pulse", label: "Running" },
  completed: { dot: "bg-completed", label: "Completed" },
  failed: { dot: "bg-failed", label: "Failed" },
  skipped: { dot: "bg-skipped", label: "Skipped" },
  cancelled: { dot: "bg-cancelled", label: "Cancelled" },
};

export function StatusIndicator({
  state,
  label,
  className,
}: {
  state: IndicatorState;
  label?: string;
  className?: string;
}) {
  const style = STYLES[state];
  return (
    <span className={cn("inline-flex items-center gap-2 text-[13px] text-muted", className)}>
      <span aria-hidden className={cn("size-2 rounded-full", style.dot)} />
      <span>{label ?? style.label}</span>
    </span>
  );
}
