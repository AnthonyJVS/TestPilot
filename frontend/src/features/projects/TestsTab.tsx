import { FileText, Plus, Search } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { NavLink, useNavigate, useOutletContext, useParams } from "react-router";

import { ErrorState } from "@/components/common/ErrorState";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { CaseSummary, Project } from "@/types/api";

import { useCreateCase, useCreateSuite, useSuites } from "./api";
import { CaseEditor } from "./CaseEditor";

type StatusFilter = "all" | CaseSummary["status"];

const STATUS_LABEL: Record<CaseSummary["status"], string> = {
  draft: "No plan",
  planned: "Plan in review",
  approved: "Approved",
};

const STATUS_DOT: Record<CaseSummary["status"], string> = {
  draft: "bg-waiting",
  planned: "bg-queued",
  approved: "bg-completed",
};

function NewTestDialog({
  projectId,
  suites,
  open,
  onOpenChange,
}: {
  projectId: string;
  suites: { id: string; name: string }[];
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const [name, setName] = useState("");
  const [suiteId, setSuiteId] = useState(suites[0]?.id ?? "");
  const [scenario, setScenario] = useState("");
  const create = useCreateCase(projectId);
  const navigate = useNavigate();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate(
      { suite_id: suiteId, name, scenario },
      {
        onSuccess: (testCase) => {
          onOpenChange(false);
          navigate(`/projects/${projectId}/tests/${testCase.id}`);
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="New test"
        description="Describe what a user does and what should happen. You can refine it later."
        footer={
          <>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" form="new-test" disabled={create.isPending || !suiteId}>
              {create.isPending ? "Creating…" : "Create test"}
            </Button>
          </>
        }
      >
        <form id="new-test" onSubmit={submit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="test-name">Name</Label>
            <Input id="test-name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="test-suite">Suite</Label>
            <NativeSelect id="test-suite" value={suiteId} onChange={(e) => setSuiteId(e.target.value)}>
              {suites.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="test-scenario">Scenario</Label>
            <textarea
              id="test-scenario"
              value={scenario}
              onChange={(e) => setScenario(e.target.value)}
              rows={4}
              maxLength={8000}
              placeholder="Open the login page, sign in with the test account and check that the dashboard greets the user."
              className="w-full rounded-control border border-border-strong bg-sunken px-3 py-2 text-sm placeholder:text-faint focus-visible:border-beacon focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-beacon-soft"
            />
          </div>
          {create.error ? (
            <p role="alert" className="text-sm text-failed">
              {create.error instanceof ApiError ? create.error.message : "Could not create the test."}
            </p>
          ) : null}
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function TestsTab() {
  const project = useOutletContext<Project>();
  const { caseId } = useParams();
  const suites = useSuites(project.id);
  const createSuite = useCreateSuite(project.id);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [creating, setCreating] = useState(false);
  const [newSuite, setNewSuite] = useState("");

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (suites.data ?? []).map((suite) => ({
      ...suite,
      cases: suite.cases.filter(
        (c) => (status === "all" || c.status === status) && (!needle || c.name.toLowerCase().includes(needle)),
      ),
    }));
  }, [suites.data, query, status]);
  const total = (suites.data ?? []).reduce((n, s) => n + s.cases.length, 0);

  const addSuite = (event: FormEvent) => {
    event.preventDefault();
    if (newSuite.trim()) createSuite.mutate(newSuite.trim(), { onSuccess: () => setNewSuite("") });
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[300px_minmax(0,1fr)]">
      <aside aria-label="Tests" className="space-y-4">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" aria-hidden />
            <Input
              aria-label="Search tests"
              placeholder="Search tests"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="h-9 pl-9"
            />
          </div>
          <Button size="sm" className="h-9" onClick={() => setCreating(true)} disabled={!suites.data?.length}>
            <Plus /> New test
          </Button>
        </div>
        <div role="radiogroup" aria-label="Filter by status" className="flex flex-wrap gap-1.5">
          {(["all", "draft", "planned", "approved"] as const).map((value) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={status === value}
              onClick={() => setStatus(value)}
              className={cn(
                "rounded-full border px-2.5 py-1 text-xs transition-colors",
                status === value ? "border-beacon bg-beacon-soft text-text" : "border-border-strong text-muted hover:text-text",
              )}
            >
              {value === "all" ? "All" : STATUS_LABEL[value]}
            </button>
          ))}
        </div>

        {suites.isPending ? (
          <Skeleton className="h-48 rounded-panel" />
        ) : suites.error ? (
          <ErrorState error={suites.error} onRetry={() => void suites.refetch()} />
        ) : (
          <div className="space-y-4">
            {filtered.map((suite) => (
              <section key={suite.id} aria-labelledby={`suite-${suite.id}`}>
                <h2 id={`suite-${suite.id}`} className="mb-1.5 text-[13px] font-semibold text-muted [font-stretch:100%]">
                  {suite.name}
                </h2>
                {suite.cases.length ? (
                  <ul className="space-y-0.5">
                    {suite.cases.map((c) => (
                      <li key={c.id}>
                        <NavLink
                          to={`/projects/${project.id}/tests/${c.id}`}
                          className={({ isActive }) =>
                            cn(
                              "flex items-center gap-2.5 rounded-control px-2.5 py-2 text-sm",
                              isActive ? "bg-raised text-text" : "text-muted hover:bg-raised/60 hover:text-text",
                            )
                          }
                        >
                          <span aria-hidden className={cn("size-2 shrink-0 rounded-full", STATUS_DOT[c.status])} />
                          <span className="min-w-0 flex-1 truncate">{c.name}</span>
                          <span className="sr-only">{STATUS_LABEL[c.status]}</span>
                          {c.current_version ? <span className="text-xs text-faint">v{c.current_version}</span> : null}
                        </NavLink>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="px-2.5 py-1 text-xs text-faint">{total ? "No matching tests" : "No tests yet"}</p>
                )}
              </section>
            ))}
            <form onSubmit={addSuite} className="flex gap-2 border-t border-border pt-4">
              <Input
                aria-label="New suite name"
                placeholder="New suite"
                value={newSuite}
                onChange={(e) => setNewSuite(e.target.value)}
                className="h-8"
              />
              <Button type="submit" variant="secondary" size="sm" disabled={!newSuite.trim() || createSuite.isPending}>
                Add suite
              </Button>
            </form>
            {createSuite.error ? (
              <p role="alert" className="text-xs text-failed">
                {createSuite.error instanceof ApiError ? createSuite.error.message : "Could not add the suite."}
              </p>
            ) : null}
          </div>
        )}
      </aside>

      <div className="min-w-0">
        {caseId ? (
          <CaseEditor key={caseId} project={project} caseId={caseId} suites={suites.data ?? []} />
        ) : (
          <div className="rounded-panel border border-dashed border-border-strong px-6 py-10">
            <FileText className="size-6 text-faint" aria-hidden />
            <p className="mt-3 font-medium">{total ? "Select a test" : "Write your first test"}</p>
            <p className="mt-1 max-w-lg text-[14px] text-muted">
              Describe a scenario in plain language. TestPilot analyses it with your AI model, proposes a structured
              plan you can edit, and renders Playwright code once you approve it.
            </p>
            {!total ? (
              <Button className="mt-5" onClick={() => setCreating(true)} disabled={!suites.data?.length}>
                <Plus /> New test
              </Button>
            ) : null}
          </div>
        )}
      </div>

      {creating && suites.data ? (
        <NewTestDialog projectId={project.id} suites={suites.data} open={creating} onOpenChange={setCreating} />
      ) : null}
    </div>
  );
}
