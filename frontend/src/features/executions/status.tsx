import { StatusIndicator, type IndicatorState } from "@/components/common/StatusIndicator";
import type { ExecutionStatus, ExecutionStep } from "@/types/api";

const RUN: Record<ExecutionStatus, { state: IndicatorState; label: string }> = {
  queued: { state: "queued", label: "Queued" },
  running: { state: "running", label: "Running" },
  passed: { state: "completed", label: "Passed" },
  failed: { state: "failed", label: "Failed" },
  error: { state: "failed", label: "Error" },
  cancelled: { state: "cancelled", label: "Cancelled" },
};

const STEP: Record<ExecutionStep["status"], { state: IndicatorState; label: string }> = {
  pending: { state: "waiting", label: "Pending" },
  running: { state: "running", label: "Running" },
  passed: { state: "completed", label: "Passed" },
  failed: { state: "failed", label: "Failed" },
  skipped: { state: "skipped", label: "Skipped" },
};

export function RunStatus({ status, className }: { status: ExecutionStatus; className?: string }) {
  const { state, label } = RUN[status];
  return <StatusIndicator state={state} label={label} className={className} />;
}

export function StepStatus({ status }: { status: ExecutionStep["status"] }) {
  const { state, label } = STEP[status];
  return <StatusIndicator state={state} label={label} />;
}
