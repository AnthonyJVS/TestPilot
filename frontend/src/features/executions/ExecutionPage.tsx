import { AlertTriangle, Download, ExternalLink, FileArchive, Image as ImageIcon, Loader2, Radio, Square } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";

import { ErrorState } from "@/components/common/ErrorState";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatDateTime } from "@/lib/utils";
import type { Artifact, Execution, ExecutionEvent, ExecutionStep } from "@/types/api";

import { downloadArtifact, TERMINAL, useArtifactUrl, useCancelRun, useExecution, useExecutionEvents, type StreamState } from "./api";
import { BROWSER_LABELS, formatMs } from "./format";
import { RunStatus, StepStatus } from "./status";

const ARTIFACT_LABELS: Record<Artifact["kind"], string> = {
  screenshot: "Screenshot",
  trace: "Playwright trace",
  video: "Video",
  network_log: "Network log",
  console_log: "Console log",
};

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function ExecutionPage() {
  const { executionId = "" } = useParams();
  const execution = useExecution(executionId);
  const { events, state } = useExecutionEvents(executionId);

  if (execution.isPending) return <Skeleton className="mx-auto h-64 max-w-7xl rounded-panel" />;
  if (execution.error) {
    return (
      <div className="mx-auto max-w-3xl">
        <ErrorState error={execution.error} title="This run could not be opened" onRetry={() => void execution.refetch()} />
      </div>
    );
  }
  return <ExecutionView execution={execution.data} events={events} streamState={state} />;
}

function ExecutionView({ execution, events, streamState }: { execution: Execution; events: ExecutionEvent[]; streamState: StreamState }) {
  const test = execution.test;
  const live = !TERMINAL.has(execution.status);
  const cancel = useCancelRun(execution.id);
  const [selected, setSelected] = useState<number | null>(null);

  const shots = useMemo(() => {
    const byStep = new Map<number, Artifact>();
    for (const artifact of execution.artifacts) {
      if (artifact.kind !== "screenshot" || artifact.step_index === null) continue;
      // Prefer the per-step frame (JPEG) over named full-page screenshots for the preview.
      const current = byStep.get(artifact.step_index);
      if (!current || artifact.content_type === "image/jpeg") byStep.set(artifact.step_index, artifact);
    }
    return byStep;
  }, [execution.artifacts]);

  const latestStep = Math.max(-1, ...shots.keys());
  const previewIndex = selected ?? (latestStep >= 0 ? latestStep : null);
  const previewStep = previewIndex !== null ? test.steps[previewIndex] : undefined;
  const files = execution.artifacts.filter((a) => a.kind !== "screenshot" || a.content_type === "image/png");
  const progress = test.steps_total ? (test.steps.filter((s) => s.status !== "pending" && s.status !== "running").length / test.steps_total) * 100 : 0;

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <header className="space-y-3">
        <p className="text-[13px] text-faint">
          <Link to="/executions" className="hover:text-text">
            Executions
          </Link>
          {test.test_case_id ? (
            <>
              {" / "}
              <Link to={`/projects/${execution.project_id}/tests/${test.test_case_id}`} className="hover:text-text">
                {test.test_name}
              </Link>
            </>
          ) : null}
        </p>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-[26px] font-semibold">
              {test.test_name} <span className="font-normal text-faint">v{test.version_number}</span>
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
          <span>{test.environment_name}</span>
          <span className="font-mono">{test.base_url}</span>
          <span>
            {BROWSER_LABELS[test.browser]} {test.browser_version ?? ""}
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

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        <section aria-labelledby="steps-heading" className="space-y-3">
          <h2 id="steps-heading" className="text-[15px] font-semibold [font-stretch:100%]">
            Steps <span className="font-normal text-faint">{test.steps_passed}/{test.steps_total} passed</span>
          </h2>
          <ol className="divide-y divide-border overflow-hidden rounded-panel border border-border bg-panel">
            {test.steps.map((step) => (
              <StepRow
                key={step.index}
                step={step}
                hasShot={shots.has(step.index)}
                selected={previewIndex === step.index}
                onSelect={() => setSelected(step.index === selected ? null : step.index)}
              />
            ))}
          </ol>
        </section>

        <section aria-labelledby="preview-heading" className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 id="preview-heading" className="text-[15px] font-semibold [font-stretch:100%]">
              Browser preview
            </h2>
            {selected !== null ? (
              <Button variant="ghost" size="sm" onClick={() => setSelected(null)}>
                Follow latest
              </Button>
            ) : null}
          </div>
          <Preview artifact={previewIndex !== null ? shots.get(previewIndex) : undefined} step={previewStep} live={live} />
        </section>
      </div>

      <Timeline events={events} />

      <section aria-labelledby="artifacts-heading" className="space-y-3">
        <h2 id="artifacts-heading" className="text-[15px] font-semibold [font-stretch:100%]">
          Artifacts
        </h2>
        {files.length === 0 ? (
          <p className="text-[13px] text-faint">{live ? "Artifacts appear when the run finishes." : "No downloadable artifacts."}</p>
        ) : (
          <ul className="divide-y divide-border overflow-hidden rounded-panel border border-border bg-panel">
            {files.map((artifact) => (
              <li key={artifact.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                <div className="flex min-w-0 items-center gap-3">
                  <FileArchive className="size-4 shrink-0 text-faint" aria-hidden />
                  <div className="min-w-0">
                    <p className="text-sm">{ARTIFACT_LABELS[artifact.kind]}</p>
                    <p className="truncate font-mono text-xs text-faint">
                      {artifact.name} · {formatBytes(artifact.size_bytes)}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  {artifact.kind === "trace" ? (
                    <a
                      href="https://trace.playwright.dev/"
                      target="_blank"
                      rel="noreferrer noopener"
                      className="inline-flex items-center gap-1 text-xs text-muted hover:text-text"
                    >
                      Open the trace viewer <ExternalLink className="size-3" aria-hidden />
                    </a>
                  ) : null}
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() =>
                      void downloadArtifact(artifact.id, artifact.name).catch((error: Error) => toast.error(error.message))
                    }
                  >
                    <Download /> Download
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function LiveBadge({ state, live }: { state: StreamState; live: boolean }) {
  if (!live) return null;
  const label = state === "open" ? "Live" : state === "reconnecting" || state === "connecting" ? "Connecting…" : "Updates paused";
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs", state === "open" ? "border-running/40 text-running" : "border-border text-faint")}>
      <Radio className={cn("size-3.5", state === "open" && "animate-pulse")} aria-hidden /> {label}
    </span>
  );
}

function StepRow({ step, hasShot, selected, onSelect }: { step: ExecutionStep; hasShot: boolean; selected: boolean; onSelect: () => void }) {
  return (
    <li className={cn(selected && "bg-raised/60")}>
      <button type="button" onClick={onSelect} className="grid w-full grid-cols-[2rem_1fr_auto] gap-x-3 gap-y-1 px-4 py-3 text-left hover:bg-raised/40">
        <span className="pt-0.5 font-mono text-xs text-faint">{step.index + 1}</span>
        <span className="min-w-0">
          <span className="block text-sm">{step.description}</span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-3 text-xs text-faint">
            <span className="font-mono">{step.action}</span>
            {step.duration_ms !== null ? <span className="font-mono">{formatMs(step.duration_ms)}</span> : null}
            {hasShot ? (
              <span className="inline-flex items-center gap-1">
                <ImageIcon className="size-3" aria-hidden /> screenshot
              </span>
            ) : null}
          </span>
        </span>
        <StepStatus status={step.status} />
        {step.error_message ? (
          <pre className="col-span-3 mt-1 max-h-48 overflow-auto rounded-control border border-failed/30 bg-failed/5 p-2.5 font-mono text-[12px] leading-5 whitespace-pre-wrap break-words text-failed">
            {step.error_message}
          </pre>
        ) : null}
      </button>
    </li>
  );
}

function Preview({ artifact, step, live }: { artifact: Artifact | undefined; step: ExecutionStep | undefined; live: boolean }) {
  const image = useArtifactUrl(artifact?.id);
  return (
    <figure className="overflow-hidden rounded-panel border border-border bg-panel">
      <div className="flex items-center gap-2 border-b border-border bg-raised/60 px-3 py-2">
        <span className="flex gap-1" aria-hidden>
          <span className="size-2.5 rounded-full bg-border-strong" />
          <span className="size-2.5 rounded-full bg-border-strong" />
          <span className="size-2.5 rounded-full bg-border-strong" />
        </span>
        <span className="min-w-0 flex-1 truncate rounded-control bg-sunken px-2.5 py-1 font-mono text-xs text-muted">{step?.url ?? "about:blank"}</span>
      </div>
      <div className="relative aspect-[16/10] bg-sunken">
        {image.url ? (
          <img src={image.url} alt={step ? `Page after step ${step.index + 1}: ${step.description}` : "Page screenshot"} className="size-full object-contain object-top" />
        ) : (
          <div className="flex size-full items-center justify-center text-[13px] text-faint">
            {image.loading ? (
              <Loader2 className="size-5 animate-spin" aria-label="Loading screenshot" />
            ) : image.failed ? (
              "The screenshot could not be loaded."
            ) : live ? (
              "Waiting for the first screenshot…"
            ) : (
              "No screenshot for this step."
            )}
          </div>
        )}
      </div>
      <figcaption className="border-t border-border px-3 py-2 text-xs text-faint">
        {step ? `After step ${step.index + 1}: ${step.description}` : "Real screenshots from the run appear here after each step."}
      </figcaption>
    </figure>
  );
}

const FILTERS = [
  ["all", "All"],
  ["steps", "Steps"],
  ["page", "Console and network"],
  ["system", "System"],
] as const;
type Filter = (typeof FILTERS)[number][0];

function matches(event: ExecutionEvent, filter: Filter): boolean {
  if (filter === "all") return true;
  if (filter === "steps") return event.type.startsWith("browser.step") || event.type === "browser.frame";
  if (filter === "page") return /^browser\.(console|network|request)/.test(event.type);
  return event.category === "system" || event.category === "node";
}

function Timeline({ events }: { events: ExecutionEvent[] }) {
  const [filter, setFilter] = useState<Filter>("all");
  const start = events[0] ? new Date(events[0].ts).getTime() : 0;
  const shown = events.filter((e) => matches(e, filter));
  return (
    <section aria-labelledby="timeline-heading" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="timeline-heading" className="text-[15px] font-semibold [font-stretch:100%]">
          Timeline <span className="font-normal text-faint">{events.length} events</span>
        </h2>
        <div role="group" aria-label="Filter events" className="flex flex-wrap gap-1">
          {FILTERS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs transition-colors",
                filter === value ? "border-beacon bg-beacon-soft text-text" : "border-border text-muted hover:text-text",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <ol className="max-h-[28rem] overflow-auto rounded-panel border border-border bg-panel font-mono text-[12px] leading-5">
        {shown.length === 0 ? <li className="px-4 py-3 text-faint">No events yet.</li> : null}
        {shown.map((event) => (
          <li key={event.seq} className="grid grid-cols-[4.5rem_1fr] gap-3 border-b border-border/60 px-4 py-1.5 last:border-b-0 sm:grid-cols-[4.5rem_11rem_1fr]">
            <span className="text-faint">+{((new Date(event.ts).getTime() - start) / 1000).toFixed(2)}s</span>
            <span className="hidden truncate text-faint sm:block">{event.type}</span>
            <span className={cn("break-words", event.level === "error" ? "text-failed" : event.level === "warning" ? "text-warning" : "text-muted")}>
              {event.message}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
