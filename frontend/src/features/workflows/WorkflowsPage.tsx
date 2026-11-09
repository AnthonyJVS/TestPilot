import { ChevronRight, Loader2, Plus, Trash2, Workflow as WorkflowIcon } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";

import { ErrorState } from "@/components/common/ErrorState";
import { PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { RunStatus } from "@/features/executions/status";
import { useProjects, useSuites } from "@/features/projects/api";
import { formatRelative } from "@/lib/utils";
import type { ExecutionStatus, WorkflowCreate } from "@/types/api";

import { useCreateWorkflow, useDeleteWorkflow, useWorkflows } from "./api";

const TEMPLATES: { value: WorkflowCreate["template"]; label: string; hint: string }[] = [
  { value: "run_test", label: "Run a test", hint: "Launch a browser, run an approved test, inspect the console, branch on failure." },
  { value: "generate_and_run", label: "Generate and run with AI", hint: "Scenario → requirement analysis → test plan → run it in the browser." },
  { value: "blank", label: "Blank canvas", hint: "Start from scratch." },
];

export function WorkflowsPage() {
  const workflows = useWorkflows();
  const remove = useDeleteWorkflow();
  const [open, setOpen] = useState(false);

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Workflow Studio"
        description="Connect AI, browser, test and logic nodes into pipelines, then run them and watch every node live."
        actions={
          <Button onClick={() => setOpen(true)}>
            <Plus /> New workflow
          </Button>
        }
      />
      {workflows.isPending ? (
        <Skeleton className="h-32 rounded-panel" />
      ) : workflows.error ? (
        <ErrorState error={workflows.error} title="Workflows could not be loaded" onRetry={() => void workflows.refetch()} />
      ) : workflows.data.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-panel border border-dashed border-border px-6 py-12 text-center">
          <WorkflowIcon className="size-8 text-faint" aria-hidden />
          <p className="max-w-md text-[13px] text-muted">No workflows yet. Start from a template: run an approved test with failure handling, or let AI plan a test and run it.</p>
          <Button onClick={() => setOpen(true)}>
            <Plus /> New workflow
          </Button>
        </div>
      ) : (
        <ul className="divide-y divide-border overflow-hidden rounded-panel border border-border bg-panel">
          {workflows.data.map((w) => (
            <li key={w.id} className="flex items-center gap-2 pr-2">
              <Link to={`/workflows/${w.id}`} className="grid min-w-0 flex-1 grid-cols-[1fr_auto] items-center gap-3 px-4 py-3 hover:bg-raised/50 sm:grid-cols-[1fr_9rem_auto]">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{w.name}</p>
                  <p className="truncate text-xs text-faint">
                    {w.project_name} · v{w.latest_version} · {w.nodes} nodes · edited {formatRelative(w.updated_at)}
                  </p>
                </div>
                <div className="hidden text-xs sm:block">
                  {w.last_run_status ? <RunStatus status={w.last_run_status as ExecutionStatus} /> : <span className="text-faint">Never run</span>}
                </div>
                <ChevronRight className="size-4 text-faint" aria-hidden />
              </Link>
              <Button
                variant="ghost"
                size="icon"
                className="size-8"
                aria-label={`Delete ${w.name}`}
                onClick={() => {
                  if (window.confirm(`Delete "${w.name}" and its versions? Past runs stay in Executions.`)) {
                    remove.mutate(w.id, { onSuccess: () => toast.success("Workflow deleted") });
                  }
                }}
              >
                <Trash2 />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        {open ? <NewWorkflowDialog /> : null}
      </Dialog>
    </div>
  );
}

function NewWorkflowDialog() {
  const navigate = useNavigate();
  const projects = useProjects();
  const create = useCreateWorkflow();
  const [projectId, setProjectId] = useState("");
  const [name, setName] = useState("");
  const [template, setTemplate] = useState<WorkflowCreate["template"]>("run_test");
  const [caseId, setCaseId] = useState("");
  const project = projectId || projects.data?.[0]?.id || "";
  const suites = useSuites(project);
  const approved = (suites.data ?? []).flatMap((s) => s.cases).filter((c) => c.status === "approved");

  const submit = () =>
    create.mutate(
      {
        projectId: project,
        body: { description: "", name: name || TEMPLATES.find((t) => t.value === template)!.label, template, test_case_id: template === "run_test" ? caseId || approved[0]?.id || null : null },
      },
      {
        onSuccess: (workflow) => {
          toast.success("Workflow created");
          void navigate(`/workflows/${workflow.id}`);
        },
      },
    );

  return (
    <DialogContent
      title="New workflow"
      footer={
        <Button onClick={submit} disabled={create.isPending || !project} form="new-workflow">
          {create.isPending ? <Loader2 className="animate-spin" /> : <Plus />} Create
        </Button>
      }
    >
      <div className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="wf-project">Project</Label>
          <NativeSelect id="wf-project" value={project} onChange={(e) => setProjectId(e.target.value)}>
            {(projects.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </NativeSelect>
          {projects.data?.length === 0 ? <p className="text-xs text-warning">Create a project first.</p> : null}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="wf-name">Name</Label>
          <Input id="wf-name" value={name} maxLength={120} placeholder="e.g. Checkout smoke test" onChange={(e) => setName(e.target.value)} />
        </div>
        <fieldset className="space-y-2">
          <legend className="mb-1 text-sm font-medium">Start from</legend>
          {TEMPLATES.map((t) => (
            <label key={t.value} className="flex cursor-pointer gap-3 rounded-control border border-border px-3 py-2 has-[:checked]:border-beacon">
              <input type="radio" name="template" value={t.value} checked={template === t.value} onChange={() => setTemplate(t.value)} className="mt-1 accent-[var(--beacon)]" />
              <span>
                <span className="text-sm">{t.label}</span>
                <span className="block text-xs text-faint">{t.hint}</span>
              </span>
            </label>
          ))}
        </fieldset>
        {template === "run_test" ? (
          <div className="space-y-1.5">
            <Label htmlFor="wf-case">Test</Label>
            <NativeSelect id="wf-case" value={caseId || approved[0]?.id || ""} onChange={(e) => setCaseId(e.target.value)}>
              {approved.length === 0 ? <option value="">No approved tests in this project</option> : null}
              {approved.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </NativeSelect>
          </div>
        ) : null}
        {create.error ? (
          <p role="alert" className="text-[13px] text-failed">
            {create.error.message}
          </p>
        ) : null}
      </div>
    </DialogContent>
  );
}
