import { ChevronRight, Shuffle } from "lucide-react";
import { useState } from "react";

import { ErrorState } from "@/components/common/ErrorState";
import { StatusIndicator } from "@/components/common/StatusIndicator";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatDateTime, formatRelative } from "@/lib/utils";
import type { AIRequestEntry } from "@/types/api";

import { useAIRequests } from "./api";

const TASK_LABELS: Record<string, string> = {
  requirement_analysis: "Requirement analysis",
  test_planning: "Test planning",
  code_generation: "Code generation",
  failure_analysis: "Failure analysis",
  visual_analysis: "Visual analysis",
  test_repair: "Test repair",
  report_generation: "Report generation",
};

const ORIGINS: Record<string, string> = { routing_check: "Routing check", task: "Task" };

function Json({ value }: { value: unknown }) {
  return (
    <pre className="max-h-64 overflow-auto rounded-control border border-border bg-sunken p-3 font-mono text-[12px] leading-5 whitespace-pre-wrap break-words text-muted">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function RequestDetails({ entry }: { entry: AIRequestEntry }) {
  return (
    <div className="grid gap-4 bg-raised/40 px-4 py-4 lg:grid-cols-2">
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[13px] lg:col-span-2">
        <dt className="text-faint">Requested</dt>
        <dd className="font-mono">
          {entry.requested_provider_type}/{entry.requested_model}
        </dd>
        <dt className="text-faint">Answered by</dt>
        <dd className="font-mono">
          {entry.actual_provider_type ? `${entry.actual_provider_type}/${entry.actual_model}` : "No answer"}
        </dd>
        <dt className="text-faint">Provider request ID</dt>
        <dd className="font-mono break-all">{entry.provider_request_id ?? "Not returned"}</dd>
        <dt className="text-faint">Attempts</dt>
        <dd>{entry.attempts}</dd>
        <dt className="text-faint">Tokens</dt>
        <dd>
          {entry.total_tokens != null
            ? `${entry.input_tokens ?? "?"} in, ${entry.output_tokens ?? "?"} out`
            : "Not reported by the provider"}
        </dd>
        <dt className="text-faint">Cost</dt>
        <dd>Not estimated (no verified price data)</dd>
        <dt className="text-faint">Started</dt>
        <dd>{formatDateTime(entry.started_at)}</dd>
        {entry.fallback_reason ? (
          <>
            <dt className="text-faint">Fallback reason</dt>
            <dd>{entry.fallback_reason}</dd>
          </>
        ) : null}
        {entry.error_message ? (
          <>
            <dt className="text-faint">Error</dt>
            <dd className="text-failed">{entry.error_message}</dd>
          </>
        ) : null}
      </dl>
      {entry.retry_history.length ? (
        <div className="lg:col-span-2">
          <p className="mb-1.5 text-xs font-medium text-muted">Retry and fallback history</p>
          <Json value={entry.retry_history} />
        </div>
      ) : null}
      <div>
        <p className="mb-1.5 text-xs font-medium text-muted">Sent (sanitized)</p>
        {entry.request_preview ? <Json value={entry.request_preview} /> : <p className="text-[13px] text-faint">Not stored (payload copies are off).</p>}
      </div>
      <div>
        <p className="mb-1.5 text-xs font-medium text-muted">Received (validated output)</p>
        {entry.response_preview ? <Json value={entry.response_preview} /> : <p className="text-[13px] text-faint">Nothing stored.</p>}
      </div>
    </div>
  );
}

function Row({ entry }: { entry: AIRequestEntry }) {
  const [open, setOpen] = useState(false);
  const switched = entry.fallback_used;
  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="grid w-full grid-cols-[auto_1fr_auto] items-center gap-3 px-4 py-3 text-left hover:bg-raised/50 md:grid-cols-[auto_1.2fr_1.5fr_auto_auto]"
      >
        <ChevronRight className={cn("size-4 text-faint transition-transform", open && "rotate-90")} aria-hidden />
        <div className="min-w-0">
          <p className="truncate text-sm">{entry.task ? (TASK_LABELS[entry.task] ?? entry.task) : "Request"}</p>
          <p className="text-xs text-faint">{ORIGINS[entry.origin] ?? entry.origin}</p>
        </div>
        <p className="hidden min-w-0 truncate font-mono text-[12px] text-muted md:block">
          {entry.actual_model ?? entry.requested_model}
          {switched ? (
            <span className="ml-2 inline-flex items-center gap-1 font-sans text-warning">
              <Shuffle className="size-3" aria-hidden /> fallback
            </span>
          ) : null}
        </p>
        <StatusIndicator
          state={entry.status === "success" ? "completed" : entry.status === "running" ? "running" : "failed"}
          label={entry.status === "success" ? `${entry.latency_ms ?? "?"} ms` : (entry.error_code ?? entry.status)}
          className="text-xs"
        />
        <time dateTime={entry.started_at} className="hidden text-xs text-faint md:block" title={formatDateTime(entry.started_at)}>
          {formatRelative(entry.started_at)}
        </time>
      </button>
      {open ? <RequestDetails entry={entry} /> : null}
    </li>
  );
}

/** Every AI call TestPilot made for this account: what was asked, which model answered, and how. */
export function AIActivity() {
  const { data, error, isPending, refetch, hasNextPage, fetchNextPage, isFetchingNextPage } = useAIRequests();
  if (isPending) return <Skeleton className="h-32 rounded-panel" />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  const entries = data.pages.flatMap((p) => p.items);
  if (!entries.length) {
    return (
      <p className="rounded-panel border border-dashed border-border-strong px-5 py-6 text-sm text-muted">
        No AI requests yet. Run a routing check to make the first one.
      </p>
    );
  }
  return (
    <div className="rounded-panel border border-border bg-panel">
      <ul className="divide-y divide-border">
        {entries.map((entry) => (
          <Row key={entry.id} entry={entry} />
        ))}
      </ul>
      {hasNextPage ? (
        <div className="border-t border-border px-4 py-2.5">
          <Button variant="ghost" size="sm" onClick={() => void fetchNextPage()} disabled={isFetchingNextPage}>
            {isFetchingNextPage ? "Loading…" : "Show older requests"}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
