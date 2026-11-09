import { ChevronRight, MonitorPlay } from "lucide-react";
import { Link } from "react-router";

import { ErrorState } from "@/components/common/ErrorState";
import { Skeleton } from "@/components/ui/skeleton";
import { formatRelative } from "@/lib/utils";

import { useExecutions } from "./api";
import { BROWSER_LABELS, formatMs } from "./format";
import { RunStatus } from "./status";

export function ExecutionsList({
  projectId,
  caseId,
  limit,
  showTest = true,
  emptyHint,
}: {
  projectId?: string;
  caseId?: string;
  limit?: number;
  showTest?: boolean;
  emptyHint?: string;
}) {
  const runs = useExecutions({ projectId, caseId, limit });

  if (runs.isPending) return <Skeleton className="h-24 rounded-panel" />;
  if (runs.error) return <ErrorState error={runs.error} title="Runs could not be loaded" onRetry={() => void runs.refetch()} />;
  if (runs.data.length === 0) {
    return (
      <div className="flex items-center gap-3 rounded-panel border border-dashed border-border px-5 py-6 text-[13px] text-muted">
        <MonitorPlay className="size-5 text-faint" aria-hidden />
        {emptyHint ?? "No runs yet. Approve a test plan, then use Run test."}
      </div>
    );
  }

  return (
    <ul className="divide-y divide-border overflow-hidden rounded-panel border border-border bg-panel">
      {runs.data.map((run) => (
        <li key={run.id}>
          <Link
            to={`/executions/${run.id}`}
            className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1 px-4 py-3 hover:bg-raised/50 sm:grid-cols-[7.5rem_1fr_auto_auto]"
          >
            <RunStatus status={run.status} />
            <div className="min-w-0 sm:order-none">
              {showTest ? (
                <p className="truncate text-sm font-medium">
                  {run.test_name} <span className="font-normal text-faint">v{run.version_number}</span>
                </p>
              ) : (
                <p className="text-sm">Version {run.version_number}</p>
              )}
              <p className="truncate text-xs text-faint">
                {run.environment_name} · {BROWSER_LABELS[run.browser] ?? run.browser} · {run.steps_passed}/{run.steps_total} steps
                {run.error_message && run.status !== "passed" ? ` · ${run.error_message}` : ""}
              </p>
            </div>
            <div className="hidden text-right text-xs text-faint sm:block">
              <p>{formatRelative(run.created_at)}</p>
              <p className="font-mono">{formatMs(run.duration_ms)}</p>
            </div>
            <ChevronRight className="hidden size-4 text-faint sm:block" aria-hidden />
          </Link>
        </li>
      ))}
    </ul>
  );
}
