import { Download, ExternalLink, FileText } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { ErrorState } from "@/components/common/ErrorState";
import { PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { TERMINAL, useExecutions } from "@/features/executions/api";
import { formatMs } from "@/features/executions/format";
import { RunStatus } from "@/features/executions/status";
import { formatDateTime } from "@/lib/utils";

import { downloadReport, openReport } from "./api";

export function ReportButtons({ executionId, compact = false }: { executionId: string; compact?: boolean }) {
  const [busy, setBusy] = useState(false);
  const run = (action: (id: string) => Promise<void>) => {
    setBusy(true);
    action(executionId)
      .catch((error: Error) => toast.error(error.message))
      .finally(() => setBusy(false));
  };
  return (
    <div className="flex items-center gap-2">
      <Button variant="secondary" size="sm" disabled={busy} onClick={() => run(openReport)}>
        <ExternalLink /> {compact ? "Report" : "Open report"}
      </Button>
      <Button variant="ghost" size="sm" disabled={busy} aria-label="Download report" onClick={() => run(downloadReport)}>
        <Download /> {compact ? null : "Download"}
      </Button>
    </div>
  );
}

export function ReportsPage() {
  const runs = useExecutions({ limit: 100 });
  const finished = runs.data?.filter((r) => TERMINAL.has(r.status)) ?? [];
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Reports"
        description="A self-contained HTML report for every finished run: status, steps or nodes, screenshots, console and network problems, failure analysis and the AI models used. Share it as a single file."
      />
      {runs.isPending ? (
        <Skeleton className="h-32 rounded-panel" />
      ) : runs.error ? (
        <ErrorState error={runs.error} title="Runs could not be loaded" onRetry={() => void runs.refetch()} />
      ) : finished.length === 0 ? (
        <div className="flex items-center gap-3 rounded-panel border border-dashed border-border px-5 py-6 text-[13px] text-muted">
          <FileText className="size-5 text-faint" aria-hidden /> Reports appear here when a run finishes.
        </div>
      ) : (
        <ul className="divide-y divide-border overflow-hidden rounded-panel border border-border bg-panel">
          {finished.map((run) => (
            <li key={run.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
              <RunStatus status={run.status} className="w-24" />
              <Link to={`/executions/${run.id}`} className="min-w-0 flex-1 hover:underline">
                <span className="block truncate text-sm font-medium">
                  {run.kind === "workflow" ? "Workflow · " : ""}
                  {run.test_name} <span className="font-normal text-faint">v{run.version_number}</span>
                </span>
                <span className="block text-xs text-faint">
                  {formatDateTime(run.created_at)} · {formatMs(run.duration_ms)} · {run.steps_passed}/{run.steps_total}{" "}
                  {run.kind === "workflow" ? "nodes" : "steps"}
                </span>
              </Link>
              <ReportButtons executionId={run.id} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
