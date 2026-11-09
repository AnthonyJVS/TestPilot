import { Bot, CheckCircle2, ChevronRight, Loader2, MonitorPlay, ShieldCheck, Sparkles, Wrench, X } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useRouting } from "@/features/ai-providers/api";
import { useStartRun } from "@/features/executions/api";
import { AIRequestDetails } from "@/features/executions/parts";
import { cn } from "@/lib/utils";

import {
  describeStep,
  type DiffRow,
  type EvidenceItem,
  type FailureAnalysis,
  type RepairProposal,
  useAnalyseFailure,
  useApproveRepair,
  useFailureReview,
  useProposeRepair,
  useRejectRepair,
} from "./api";

const CATEGORY: Record<string, string> = {
  locator_changed: "Locator changed",
  element_missing: "Element missing",
  timing: "Timing",
  assertion_mismatch: "Assertion mismatch",
  navigation: "Navigation",
  network: "Network",
  test_data: "Test data",
  environment: "Environment",
  application_bug: "Application bug",
  unknown: "Unknown",
};

const ACTION: Record<string, string> = {
  repair_test: "Repair the test",
  report_bug: "Report an application bug",
  retry: "Retry the run",
  fix_environment: "Fix the environment",
  needs_more_information: "More information needed",
};

const CONFIDENCE: Record<string, string> = { high: "text-completed", medium: "text-warning", low: "text-faint" };

function RouteNote({ tasks }: { tasks: string[] }) {
  const routing = useRouting();
  const routes = routing.data?.effective.filter((r) => tasks.includes(r.task)) ?? [];
  if (!routing.data) return null;
  if (routes.some((r) => !r.model)) {
    return (
      <p className="text-[13px] text-warning">
        No AI model is set for this task. <Link to="/ai-providers" className="text-beacon hover:underline">Choose one on the AI Providers page.</Link>
      </p>
    );
  }
  return (
    <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-faint">
      {routes.map((r) => (
        <span key={r.task} className="inline-flex items-center gap-1">
          <Bot className="size-3.5" aria-hidden /> {r.label}: <span className="font-mono text-muted">{r.model?.model_id}</span> ({r.model?.data_location})
        </span>
      ))}
    </p>
  );
}

/** Failure analysis and human-approved repair for a failed test run. */
export function FailurePanel({ executionId }: { executionId: string }) {
  const review = useFailureReview(executionId, true);
  const analyse = useAnalyseFailure(executionId);
  const analysis = review.data?.analysis ?? null;

  return (
    <section aria-labelledby="failure-heading" className="space-y-4 rounded-panel border border-border bg-panel p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 id="failure-heading" className="flex items-center gap-2 text-[15px] font-semibold [font-stretch:100%]">
            <Sparkles className="size-4 text-running" aria-hidden /> Why did this fail?
          </h2>
          <p className="max-w-2xl text-[13px] text-muted">
            TestPilot collects verified evidence from this run, then an AI model explains it. Evidence is fact; the AI's hypotheses are not. Nothing changes in the test without
            your approval.
          </p>
          <RouteNote tasks={["failure_analysis", "test_repair"]} />
        </div>
        <Button
          onClick={() => analyse.mutate(undefined, { onError: (e) => toast.error(e.message) })}
          disabled={analyse.isPending}
          variant={analysis ? "secondary" : "primary"}
        >
          {analyse.isPending ? <Loader2 className="animate-spin" /> : <Sparkles />} {analysis ? "Analyse again" : "Analyse failure"}
        </Button>
      </div>
      {analyse.isPending ? <p className="text-[13px] text-muted">Collecting evidence and asking the model. This usually takes 5 to 30 seconds…</p> : null}
      {analysis ? <AnalysisView analysis={analysis} executionId={executionId} proposals={review.data?.proposals ?? []} /> : null}
    </section>
  );
}

function AnalysisView({ analysis, executionId, proposals }: { analysis: FailureAnalysis; executionId: string; proposals: RepairProposal[] }) {
  const [focus, setFocus] = useState<string | null>(null);
  const propose = useProposeRepair(executionId);
  const result = analysis.result;
  const open = proposals.find((p) => p.status === "proposed") ?? proposals[0];

  return (
    <div className="space-y-5">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-2">
          <h3 className="flex items-center gap-1.5 text-[13px] font-semibold">
            <ShieldCheck className="size-4 text-completed" aria-hidden /> Verified evidence <span className="font-normal text-faint">collected from the run</span>
          </h3>
          <ol className="space-y-1.5">
            {analysis.evidence.map((item) => (
              <EvidenceRow key={item.id} item={item} highlighted={focus === item.id} />
            ))}
          </ol>
          <p className="text-xs text-faint">{analysis.used_screenshot ? "The failing step's screenshot was sent to a model with verified vision." : "No screenshot was sent (vision not verified for this model)."}</p>
        </div>
        <div className="space-y-3">
          <h3 className="flex items-center gap-1.5 text-[13px] font-semibold">
            <Sparkles className="size-4 text-running" aria-hidden /> AI explanation <span className="font-normal text-faint">hypotheses, not facts</span>
          </h3>
          {analysis.status === "failed" || !result ? (
            <p role="alert" className="text-[13px] text-failed">
              {analysis.error_message ?? "The analysis failed."}
            </p>
          ) : (
            <>
              <div className="flex flex-wrap gap-2 text-xs">
                <span className="rounded-full border border-border-strong px-2.5 py-0.5">{CATEGORY[result.category] ?? result.category}</span>
                <span className="rounded-full border border-beacon/50 px-2.5 py-0.5 text-beacon">{ACTION[result.recommended_action]}</span>
              </div>
              <p className="text-sm">{result.summary}</p>
              <ul className="space-y-2">
                {result.hypotheses.map((h, i) => (
                  <li key={i} className="rounded-control border border-border px-3 py-2 text-[13px]">
                    <p>{h.statement}</p>
                    <p className="mt-1 flex flex-wrap items-center gap-1.5 text-xs">
                      <span className={CONFIDENCE[h.confidence]}>{h.confidence} confidence</span>
                      {(h.evidence_ids ?? []).map((id) => (
                        <button
                          key={id}
                          type="button"
                          onMouseEnter={() => setFocus(id)}
                          onMouseLeave={() => setFocus(null)}
                          onFocus={() => setFocus(id)}
                          onBlur={() => setFocus(null)}
                          className="rounded bg-raised px-1.5 font-mono text-[11px] text-muted hover:text-text"
                        >
                          {id}
                        </button>
                      ))}
                    </p>
                  </li>
                ))}
              </ul>
              {result.repair_hint ? <p className="text-[13px] text-muted">Repair idea: {result.repair_hint}</p> : null}
              {analysis.ai_request_ids.map((id) => (
                <details key={id} className="text-xs">
                  <summary className="cursor-pointer text-faint">Model, tokens and sanitized prompt</summary>
                  <div className="mt-2">
                    <AIRequestDetails id={id} />
                  </div>
                </details>
              ))}
              <Button
                variant={result.recommended_action === "repair_test" ? "primary" : "secondary"}
                onClick={() => propose.mutate(analysis.id, { onError: (e) => toast.error(e.message) })}
                disabled={propose.isPending}
              >
                {propose.isPending ? <Loader2 className="animate-spin" /> : <Wrench />} Propose a fix
              </Button>
            </>
          )}
        </div>
      </div>
      {open ? <ProposalView proposal={open} executionId={executionId} /> : null}
    </div>
  );
}

function EvidenceRow({ item, highlighted }: { item: EvidenceItem; highlighted: boolean }) {
  const [open, setOpen] = useState(item.kind === "error");
  return (
    <li className={cn("rounded-control border px-3 py-1.5 transition-colors", highlighted ? "border-beacon bg-beacon-soft/40" : "border-border")}>
      <button type="button" onClick={() => setOpen(!open)} className="flex w-full items-start gap-2 text-left text-[13px]">
        <ChevronRight className={cn("mt-0.5 size-3.5 shrink-0 text-faint transition-transform", open && "rotate-90")} aria-hidden />
        <span className="font-mono text-xs text-faint">{item.id}</span>
        <span className="min-w-0 flex-1">{item.title}</span>
        <span className="text-[10px] tracking-wide text-faint uppercase">{item.kind}</span>
      </button>
      {open && item.detail ? (
        <pre className="mt-1.5 max-h-56 overflow-auto rounded-control bg-sunken p-2 font-mono text-[11px] leading-4 whitespace-pre-wrap break-words text-muted">{item.detail}</pre>
      ) : null}
    </li>
  );
}

const ROW_STYLE: Record<DiffRow["kind"], string> = {
  same: "text-faint",
  changed: "border-l-2 border-warning bg-warning/5",
  added: "border-l-2 border-completed bg-completed/5",
  removed: "border-l-2 border-failed bg-failed/5",
};

function ProposalView({ proposal, executionId }: { proposal: RepairProposal; executionId: string }) {
  const navigate = useNavigate();
  const approve = useApproveRepair(executionId);
  const reject = useRejectRepair(executionId);
  const start = useStartRun();
  const [note, setNote] = useState("");
  const [approvedVersion, setApprovedVersion] = useState<{ id: string; version: number } | null>(null);
  const errors = proposal.issues.filter((i) => i.severity === "error");

  return (
    <div className="space-y-3 rounded-panel border border-border-strong p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 text-[13px] font-semibold">
          <Wrench className="size-4 text-beacon" aria-hidden /> Proposed fix
        </h3>
        <span className="rounded-full border border-border px-2.5 py-0.5 text-xs capitalize text-muted">{proposal.status.replace("_", " ")}</span>
      </div>
      <p className="text-sm">{proposal.rationale}</p>
      {proposal.verdict === "no_test_change" ? (
        <p className="text-[13px] text-muted">The model found no test change to make: the application, not the test, looks wrong. Consider reporting a bug.</p>
      ) : null}
      {proposal.diff.length ? (
        <ol className="space-y-1 font-mono text-[12px]" aria-label="Changes to the test plan">
          {proposal.diff.map((row, i) => (
            <li key={i} className={cn("rounded-control px-3 py-1.5", ROW_STYLE[row.kind])}>
              <span className="mr-2 inline-block w-14 text-[10px] tracking-wide uppercase">{row.kind}</span>
              {row.kind === "changed" ? (
                <>
                  <span className="text-failed line-through">{describeStep(row.before)}</span>
                  <span className="mx-1.5 text-faint">→</span>
                  <span className="text-completed">{describeStep(row.after)}</span>
                </>
              ) : row.kind === "removed" ? (
                <span className="text-failed line-through">{describeStep(row.before)}</span>
              ) : (
                <span className={row.kind === "added" ? "text-completed" : undefined}>{describeStep(row.after)}</span>
              )}
              {row.reason ? <span className="block pl-16 font-sans text-[11px] text-faint">{row.reason}</span> : null}
            </li>
          ))}
        </ol>
      ) : null}
      {proposal.issues.length ? (
        <ul className="space-y-1 text-[13px]">
          {proposal.issues.map((issue, i) => (
            <li key={i} className={issue.severity === "error" ? "text-failed" : "text-warning"}>
              {issue.message}
            </li>
          ))}
        </ul>
      ) : null}
      {proposal.status === "proposed" && !approvedVersion ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            onClick={() =>
              approve.mutate(proposal.id, {
                onSuccess: (result) => {
                  setApprovedVersion({ id: result.version_id, version: result.version });
                  toast.success(`Approved as version ${result.version}`);
                },
                onError: (e) => toast.error(e.message),
              })
            }
            disabled={approve.isPending || errors.length > 0}
          >
            {approve.isPending ? <Loader2 className="animate-spin" /> : <CheckCircle2 />} Approve as a new version
          </Button>
          <Input aria-label="Reason for rejecting" placeholder="Reason (optional)" value={note} onChange={(e) => setNote(e.target.value)} className="h-9 w-56" />
          <Button variant="ghost" onClick={() => reject.mutate({ proposalId: proposal.id, note }, { onError: (e) => toast.error(e.message) })} disabled={reject.isPending}>
            <X /> Reject
          </Button>
        </div>
      ) : null}
      {approvedVersion ? (
        <div className="flex flex-wrap items-center gap-3 text-[13px]">
          <span className="text-completed">Version {approvedVersion.version} is now current.</span>
          <Button
            size="sm"
            onClick={() =>
              start.mutate(
                { versionId: approvedVersion.id, body: { environment_id: null, browser: "chromium", screenshots: "every_step", trace: true, video: false } },
                { onSuccess: (execution) => void navigate(`/executions/${execution.id}`), onError: (e) => toast.error(e.message) },
              )
            }
            disabled={start.isPending}
          >
            {start.isPending ? <Loader2 className="animate-spin" /> : <MonitorPlay />} Run version {approvedVersion.version}
          </Button>
        </div>
      ) : null}
      {proposal.status === "rejected" && proposal.decision_note ? <p className="text-xs text-faint">Rejected: {proposal.decision_note}</p> : null}
    </div>
  );
}
