import { AlertTriangle, Image as ImageIcon, Loader2, Square, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";

import { ErrorState } from "@/components/common/ErrorState";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useVersion } from "@/features/projects/api";
import { cn, formatDateTime } from "@/lib/utils";
import type { Execution, ExecutionEvent, ExecutionStep, PlanStep, TestExecution } from "@/types/api";

import { TERMINAL, useCancelRun, useExecution, useExecutionEvents, type StreamState } from "./api";
import { BROWSER_LABELS, formatMs } from "./format";
import { ArtifactsSection, Evidence, Filmstrip, LiveBadge, Preview, ReplayBar, Timeline } from "./parts";
import { frameAt, framesOf, stepStatesAt, useReplay } from "./replay";
import { RunStatus, StepStatus } from "./status";
import { WorkflowRunView } from "./WorkflowRunView";

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
  const data = execution.data;
  if (data.workflow) return <WorkflowRunView execution={data} workflow={data.workflow} events={events} streamState={state} />;
  if (!data.test) return null;
  return <ExecutionView execution={data} test={data.test} events={events} streamState={state} />;
}

export function RunHeader({
  execution,
  title,
  version,
  back,
  meta,
  streamState,
  progress,
}: {
  execution: Execution;
  title: string;
  version: number;
  back: { to: string; label: string } | null;
  meta: React.ReactNode;
  streamState: StreamState;
  progress: number;
}) {
  const live = !TERMINAL.has(execution.status);
  const cancel = useCancelRun(execution.id);
  return (
    <header className="space-y-3">
      <p className="text-[13px] text-faint">
        <Link to="/executions" className="hover:text-text">
          Executions
        </Link>
        {back ? (
          <>
            {" / "}
            <Link to={back.to} className="hover:text-text">
              {back.label}
            </Link>
          </>
        ) : null}
      </p>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-[26px] font-semibold">
            {title} <span className="font-normal text-faint">v{version}</span>
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
        {meta}
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
  );
}

function ExecutionView({ execution, test, events, streamState }: { execution: Execution; test: TestExecution; events: ExecutionEvent[]; streamState: StreamState }) {
  const live = !TERMINAL.has(execution.status);
  const replay = useReplay(events);
  const frames = useMemo(() => framesOf(events), [events]);
  const [selected, setSelected] = useState<number | null>(null);
  const version = useVersion(test.test_version_id);

  const derived = replay.replaying ? stepStatesAt(events, test.steps, replay.at) : null;
  const statusOf = (step: ExecutionStep) => derived?.get(step.index) ?? step.status;
  const frame = selected !== null ? frameAt(frames, replay.at, { stepIndex: selected }) : frameAt(frames, replay.at);
  const frameStep = frame?.stepIndex !== null && frame?.stepIndex !== undefined ? test.steps[frame.stepIndex] : undefined;
  const caption = frameStep ? `${frame?.interim ? "During" : "After"} step ${frameStep.index + 1}: ${frameStep.description}` : null;
  const finishedSteps = test.steps.filter((s) => !["pending", "running"].includes(statusOf(s))).length;
  const progress = test.steps_total ? (finishedSteps / test.steps_total) * 100 : 0;
  const withShots = new Set(frames.map((f) => f.stepIndex));
  const selectedStep = selected !== null ? test.steps[selected] : undefined;

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <RunHeader
        execution={execution}
        title={test.test_name}
        version={test.version_number}
        back={test.test_case_id ? { to: `/projects/${execution.project_id}/tests/${test.test_case_id}`, label: test.test_name } : null}
        streamState={streamState}
        progress={progress}
        meta={
          <>
            <span>{test.environment_name}</span>
            <span className="font-mono">{test.base_url}</span>
            <span>
              {BROWSER_LABELS[test.browser]} {test.browser_version ?? ""}
            </span>
          </>
        }
      />
      <ReplayBar replay={replay} events={events} live={live} />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        <section aria-labelledby="steps-heading" className="space-y-3">
          <h2 id="steps-heading" className="text-[15px] font-semibold [font-stretch:100%]">
            Steps <span className="font-normal text-faint">{test.steps_passed}/{test.steps_total} passed</span>
          </h2>
          <ol className="divide-y divide-border overflow-hidden rounded-panel border border-border bg-panel">
            {test.steps.map((step) => (
              <li key={step.index} className={cn(selected === step.index && "bg-raised/60")}>
                <button
                  type="button"
                  onClick={() => setSelected(step.index === selected ? null : step.index)}
                  className="grid w-full grid-cols-[2rem_1fr_auto] gap-x-3 gap-y-1 px-4 py-3 text-left hover:bg-raised/40"
                >
                  <span className="pt-0.5 font-mono text-xs text-faint">{step.index + 1}</span>
                  <span className="min-w-0">
                    <span className="block text-sm">{step.description}</span>
                    <span className="mt-0.5 flex flex-wrap items-center gap-x-3 text-xs text-faint">
                      <span className="font-mono">{step.action}</span>
                      {step.duration_ms !== null && !derived ? <span className="font-mono">{formatMs(step.duration_ms)}</span> : null}
                      {withShots.has(step.index) ? (
                        <span className="inline-flex items-center gap-1">
                          <ImageIcon className="size-3" aria-hidden /> screenshots
                        </span>
                      ) : null}
                    </span>
                  </span>
                  <StepStatus status={statusOf(step)} />
                  {step.error_message && statusOf(step) === "failed" ? (
                    <pre className="col-span-3 mt-1 max-h-48 overflow-auto rounded-control border border-failed/30 bg-failed/5 p-2.5 font-mono text-[12px] leading-5 whitespace-pre-wrap break-words text-failed">
                      {step.error_message}
                    </pre>
                  ) : null}
                </button>
              </li>
            ))}
          </ol>
          {selectedStep ? (
            <StepInspector
              step={selectedStep}
              plan={version.data?.plan.steps[selectedStep.index]}
              events={events.filter((e) => e.step_index === selectedStep.index && e.node_id === "execute_test")}
              frames={frames.filter((f) => f.stepIndex === selectedStep.index).length}
              onClose={() => setSelected(null)}
            />
          ) : (
            <p className="text-xs text-faint">Select a step to inspect its definition, evidence and screenshots.</p>
          )}
        </section>

        <section aria-labelledby="preview-heading" className="space-y-3">
          <h2 id="preview-heading" className="text-[15px] font-semibold [font-stretch:100%]">
            Browser preview
          </h2>
          <Preview frame={frame} caption={caption} live={live} startTs={events[0]?.ts} />
          <Filmstrip
            frames={frames}
            at={replay.at}
            onSeek={(seq) => {
              setSelected(null);
              replay.seek(seq);
            }}
            label={(f) => `Step ${(f.stepIndex ?? 0) + 1}`}
          />
        </section>
      </div>

      <Timeline events={events} at={replay.at} replaying={replay.replaying} onSeek={replay.seek} />
      <ArtifactsSection execution={execution} live={live} />
    </div>
  );
}

function StepInspector({ step, plan, events, frames, onClose }: { step: ExecutionStep; plan: PlanStep | undefined; events: ExecutionEvent[]; frames: number; onClose: () => void }) {
  return (
    <div className="space-y-3 rounded-panel border border-border bg-panel p-4 text-[13px]" aria-label={`Step ${step.index + 1} details`}>
      <div className="flex items-start justify-between gap-3">
        <p className="font-medium">
          Step {step.index + 1}: {step.description}
        </p>
        <Button variant="ghost" size="icon" className="size-7" aria-label="Close step details" onClick={onClose}>
          <X />
        </Button>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
        <dt className="text-faint">Action</dt>
        <dd className="font-mono">{step.action}</dd>
        {plan?.locator ? (
          <>
            <dt className="text-faint">Element</dt>
            <dd className="font-mono break-all">
              {plan.locator.strategy}
              {plan.locator.role ? `(${plan.locator.role})` : ""} “{plan.locator.value}”{plan.locator.exact ? " exact" : ""}
            </dd>
          </>
        ) : null}
        {plan?.value ? (
          <>
            <dt className="text-faint">Value</dt>
            <dd className="font-mono break-all">{plan.value}</dd>
          </>
        ) : null}
        <dt className="text-faint">Duration</dt>
        <dd>{formatMs(step.duration_ms)}</dd>
        <dt className="text-faint">Page</dt>
        <dd className="font-mono break-all">{step.url ?? "—"}</dd>
        <dt className="text-faint">Frames</dt>
        <dd>{frames}</dd>
      </dl>
      {plan?.value?.includes("{{") ? <p className="text-xs text-faint">Test data is shown as references; values are resolved only inside the run.</p> : null}
      <div>
        <p className="mb-1 text-xs font-medium text-muted">Console and network</p>
        <Evidence events={events} />
      </div>
    </div>
  );
}
