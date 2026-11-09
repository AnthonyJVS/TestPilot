import { Bot, Loader2, MonitorPlay, PenLine, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";

import { ErrorState } from "@/components/common/ErrorState";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { useRouting } from "@/features/ai-providers/api";
import { ExecutionsList } from "@/features/executions/ExecutionsList";
import { RunTestDialog } from "@/features/executions/RunTestDialog";
import { ApiError } from "@/lib/api-client";
import type { PlanRecord, Project, Suite, TestCase } from "@/types/api";

import { useCase, useDeleteCase, useGeneratePlan, useUpdateCase } from "./api";
import { CodeViewer } from "./CodeViewer";
import { emptyPlan } from "./plan-actions";
import { PlanEditor } from "./PlanEditor";

const TASK_NAMES: Record<string, string> = {
  requirement_analysis: "Requirement analysis",
  test_planning: "Test planning",
};

function RouteInfo() {
  const routing = useRouting();
  if (!routing.data) return null;
  const relevant = routing.data.effective.filter((r) => r.task === "requirement_analysis" || r.task === "test_planning");
  if (relevant.some((r) => !r.model || r.issues.length)) {
    return (
      <p className="text-[13px] text-warning">
        No AI model is ready for planning.{" "}
        <Link to="/ai-providers" className="font-medium text-beacon hover:underline">
          Set one up on the AI Providers page
        </Link>
        , or write the plan yourself.
      </p>
    );
  }
  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-1 text-[13px] text-muted">
      {relevant.map((r) => (
        <li key={r.task} className="inline-flex items-center gap-1.5">
          <Bot className="size-3.5 text-faint" aria-hidden />
          {TASK_NAMES[r.task]}: <span className="font-mono text-text">{r.model?.model_id}</span>
          <span className="text-faint">
            ({r.model?.provider_name}, {r.model?.data_location === "external" ? "external" : "local"})
          </span>
        </li>
      ))}
    </ul>
  );
}

function AnalysisPanel({ record }: { record: PlanRecord }) {
  const analysis = record.analysis;
  if (!analysis && record.ai_requests.length === 0) return null;
  return (
    <section aria-labelledby="analysis-heading" className="rounded-panel border border-border bg-panel px-5 py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="analysis-heading" className="text-[15px] font-semibold [font-stretch:100%]">
          AI analysis
        </h2>
        <p className="text-xs text-faint">AI output: review it before approving.</p>
      </div>
      {analysis ? (
        <>
          <p className="mt-2 text-sm">{analysis.summary}</p>
          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-muted">
            {analysis.requirements.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          {analysis.ambiguities.length ? (
            <div className="mt-3 rounded-control border border-warning/40 bg-warning/5 px-3 py-2">
              <p className="text-[13px] font-medium text-warning">Open questions</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-[13px] text-muted">
                {analysis.ambiguities.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      ) : null}
      {record.ai_requests.length ? (
        <ul className="mt-3 space-y-1 border-t border-border pt-3 text-xs text-faint">
          {record.ai_requests.map((r) => (
            <li key={r.id}>
              {TASK_NAMES[r.task ?? ""] ?? r.task}: {r.actual_provider_type ?? r.requested_provider_type}/
              <span className="font-mono">{r.actual_model ?? r.requested_model}</span>
              {r.latency_ms != null ? `, ${(r.latency_ms / 1000).toFixed(1)} s` : ""}
              {r.total_tokens != null ? `, ${r.total_tokens} tokens` : ""}
              {r.fallback_used ? ", fallback model" : ""}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function ScenarioEditor({ project, testCase, suites }: { project: Project; testCase: TestCase; suites: Suite[] }) {
  const [name, setName] = useState(testCase.name);
  const [scenario, setScenario] = useState(testCase.scenario);
  const [suiteId, setSuiteId] = useState(testCase.suite_id);
  const update = useUpdateCase(project.id, testCase.id);
  const dirty = name !== testCase.name || scenario !== testCase.scenario || suiteId !== testCase.suite_id;

  return (
    <section aria-labelledby="scenario-heading" className="space-y-3">
      <h2 id="scenario-heading" className="sr-only">
        Scenario
      </h2>
      <div className="grid gap-3 sm:grid-cols-[1fr_200px]">
        <div className="space-y-1.5">
          <Label htmlFor="case-name">Test name</Label>
          <Input id="case-name" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="case-suite">Suite</Label>
          <NativeSelect id="case-suite" value={suiteId} onChange={(e) => setSuiteId(e.target.value)}>
            {suites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="case-scenario">Scenario in plain language</Label>
        <textarea
          id="case-scenario"
          rows={4}
          maxLength={8000}
          value={scenario}
          onChange={(e) => setScenario(e.target.value)}
          placeholder="Open the login page, sign in with the test account, add a product to the cart and check the total."
          className="w-full rounded-control border border-border-strong bg-sunken px-3 py-2 text-sm leading-6 placeholder:text-faint focus-visible:border-beacon focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-beacon-soft"
        />
      </div>
      <div className="flex items-center justify-end gap-3">
        {update.error ? (
          <span className="text-[13px] text-failed">
            {update.error instanceof ApiError ? update.error.message : "Could not save."}
          </span>
        ) : null}
        <Button
          variant="secondary"
          size="sm"
          disabled={!dirty || update.isPending || !name.trim()}
          onClick={() =>
            update.mutate(
              { name, scenario, suite_id: suiteId },
              { onSuccess: () => toast.success("Test saved") },
            )
          }
        >
          {update.isPending ? "Saving…" : "Save test"}
        </Button>
      </div>
    </section>
  );
}

export function CaseEditor({ project, caseId, suites }: { project: Project; caseId: string; suites: Suite[] }) {
  const testCase = useCase(caseId);
  const generate = useGeneratePlan(project.id, caseId);
  const remove = useDeleteCase(project.id);
  const navigate = useNavigate();
  const [manual, setManual] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [runOpen, setRunOpen] = useState(false);
  const [environmentId, setEnvironmentId] = useState(
    project.environments.find((e) => e.is_default)?.id ?? project.environments[0]?.id ?? "",
  );

  if (testCase.isPending) return <Skeleton className="h-96 rounded-panel" />;
  if (testCase.error) return <ErrorState error={testCase.error} onRetry={() => void testCase.refetch()} />;
  const data = testCase.data;
  const latest = data.latest_plan;
  const currentVersion = data.versions.find((v) => v.id === data.current_version_id);
  const scenarioChanged = latest !== null && latest.scenario_snapshot !== data.scenario;

  const runGenerate = () =>
    generate.mutate(environmentId || null, {
      onSuccess: () => {
        setManual(false);
        toast.success("Plan generated. Review it before approving.");
      },
    });

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13px] text-muted">
          {data.status === "approved"
            ? `Approved, version ${data.versions.find((v) => v.id === data.current_version_id)?.version ?? "?"} is current.`
            : data.status === "planned"
              ? "A plan is waiting for review."
              : "No plan yet."}
        </p>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            disabled={!currentVersion}
            title={currentVersion ? undefined : "Approve a plan first"}
            onClick={() => setRunOpen(true)}
          >
            <MonitorPlay /> Run test
          </Button>
          <Button variant="ghost" size="icon" className="size-8" aria-label="Delete test" onClick={() => setConfirmDelete(true)}>
            <Trash2 />
          </Button>
        </div>
      </div>

      <ScenarioEditor key={data.updated_at} project={project} testCase={data} suites={suites} />

      <section aria-labelledby="generate-heading" className="space-y-3 rounded-panel border border-border bg-panel px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1.5">
            <h2 id="generate-heading" className="text-[15px] font-semibold [font-stretch:100%]">
              {latest ? "Regenerate the plan" : "Create the plan"}
            </h2>
            <RouteInfo />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {project.environments.length > 1 ? (
              <NativeSelect
                aria-label="Environment for test data"
                value={environmentId}
                onChange={(e) => setEnvironmentId(e.target.value)}
                className="w-40"
              >
                {project.environments.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.name}
                  </option>
                ))}
              </NativeSelect>
            ) : null}
            {!latest && !manual ? (
              <Button variant="secondary" onClick={() => setManual(true)}>
                <PenLine /> Write it myself
              </Button>
            ) : null}
            <Button onClick={runGenerate} disabled={generate.isPending || !data.scenario.trim()}>
              {generate.isPending ? <Loader2 className="animate-spin" /> : <Sparkles />}
              {generate.isPending ? "Analysing and planning…" : "Generate with AI"}
            </Button>
          </div>
        </div>
        {!data.scenario.trim() ? <p className="text-[13px] text-faint">Save a scenario first.</p> : null}
        {generate.isPending ? (
          <p className="text-[13px] text-muted" aria-live="polite">
            Two AI calls run in sequence: requirement analysis, then test planning. This usually takes 10 to 60 seconds.
          </p>
        ) : null}
        {generate.error ? (
          <p role="alert" className="text-[13px] text-failed">
            {generate.error instanceof ApiError ? generate.error.message : "Plan generation failed."}
          </p>
        ) : null}
        {scenarioChanged ? (
          <p className="text-[13px] text-warning">The scenario changed after this plan was created.</p>
        ) : null}
      </section>

      {latest ? <AnalysisPanel record={latest} /> : null}

      {latest ? (
        <PlanEditor key={`${latest.id}:${latest.updated_at}`} projectId={project.id} caseId={caseId} record={latest} initial={latest.plan} />
      ) : manual ? (
        <PlanEditor projectId={project.id} caseId={caseId} record={null} initial={emptyPlan(data.name)} />
      ) : null}

      {data.versions.length ? (
        <CodeViewer key={data.current_version_id ?? "none"} caseId={data.id} versions={data.versions} currentVersionId={data.current_version_id} />
      ) : null}

      {currentVersion ? (
        <section aria-labelledby="runs-heading" className="space-y-3">
          <h2 id="runs-heading" className="text-[15px] font-semibold [font-stretch:100%]">
            Recent runs
          </h2>
          <ExecutionsList caseId={caseId} limit={5} showTest={false} emptyHint="This test has not run yet." />
        </section>
      ) : null}

      <Dialog open={runOpen} onOpenChange={setRunOpen}>
        {currentVersion && runOpen ? (
          <RunTestDialog project={project} versionId={currentVersion.id} versionNumber={currentVersion.version} testName={data.name} />
        ) : null}
      </Dialog>

      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent
          title={`Delete "${data.name}"?`}
          description="Its plans and approved versions are deleted too. This cannot be undone."
          footer={
            <>
              <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
                Cancel
              </Button>
              <Button
                variant="danger"
                disabled={remove.isPending}
                onClick={() =>
                  remove.mutate(caseId, {
                    onSuccess: () => {
                      toast.success("Test deleted");
                      navigate(`/projects/${project.id}`);
                    },
                  })
                }
              >
                Delete test
              </Button>
            </>
          }
        >
          <span />
        </DialogContent>
      </Dialog>
    </div>
  );
}
