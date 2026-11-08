import { FolderKanban, Plus, Search } from "lucide-react";
import { useDeferredValue, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { ErrorState } from "@/components/common/ErrorState";
import { PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api-client";
import { formatRelative } from "@/lib/utils";

import { useCreateProject, useProjects } from "./api";

function CreateProjectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("https://");
  const [description, setDescription] = useState("");
  const create = useCreateProject();
  const navigate = useNavigate();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate(
      { name, base_url: baseUrl, description },
      { onSuccess: (project) => navigate(`/projects/${project.id}`) },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="New project"
        description="One project per website you test. You can add environments such as staging later."
        footer={
          <>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" form="create-project" disabled={create.isPending}>
              {create.isPending ? "Creating…" : "Create project"}
            </Button>
          </>
        }
      >
        <form id="create-project" onSubmit={submit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="project-name">Name</Label>
            <Input id="project-name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="project-url">Website URL</Label>
            <Input id="project-url" type="url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} required />
            <p className="text-xs text-faint">Tests may only visit this domain unless you allow more in project settings.</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="project-description">Description (optional)</Label>
            <Input id="project-description" value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          {create.error ? (
            <p role="alert" className="text-sm text-failed">
              {create.error instanceof ApiError ? create.error.message : "Could not create the project."}
            </p>
          ) : null}
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function ProjectsPage() {
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query.trim());
  const projects = useProjects(deferred);
  const [creating, setCreating] = useState(false);

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader
        title="Projects"
        description="Each project is one website under test, with its environments, test data and tests."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus /> New project
          </Button>
        }
      />

      <div className="relative mb-4 max-w-sm">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" aria-hidden />
        <Input
          aria-label="Search projects"
          placeholder="Search projects"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="pl-9"
        />
      </div>

      {projects.isPending ? (
        <Skeleton className="h-40 rounded-panel" />
      ) : projects.error ? (
        <ErrorState error={projects.error} onRetry={() => void projects.refetch()} />
      ) : projects.data.length === 0 ? (
        deferred ? (
          <p className="py-8 text-sm text-muted">No project matches “{deferred}”.</p>
        ) : (
          <div className="rounded-panel border border-dashed border-border-strong px-6 py-10">
            <FolderKanban className="size-6 text-faint" aria-hidden />
            <p className="mt-3 font-medium">Create your first project</p>
            <p className="mt-1 max-w-lg text-[14px] text-muted">
              Add the website you want to test. TestPilot then turns plain-language scenarios into reviewed,
              structured test plans and Playwright code.
            </p>
            <Button className="mt-5" onClick={() => setCreating(true)}>
              <Plus /> New project
            </Button>
          </div>
        )
      ) : (
        <ul className="divide-y divide-border rounded-panel border border-border bg-panel">
          {projects.data.map((project) => (
            <li key={project.id}>
              <Link
                to={`/projects/${project.id}`}
                className="grid gap-x-6 gap-y-1 px-5 py-4 hover:bg-raised/50 sm:grid-cols-[1fr_auto]"
              >
                <div className="min-w-0">
                  <p className="font-medium">{project.name}</p>
                  <p className="truncate font-mono text-xs text-faint">{project.base_url}</p>
                </div>
                <p className="text-[13px] text-muted sm:text-right">
                  {project.case_count} {project.case_count === 1 ? "test" : "tests"}, {project.approved_count} approved
                  <span className="block text-xs text-faint">Updated {formatRelative(project.updated_at)}</span>
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {creating ? <CreateProjectDialog open={creating} onOpenChange={setCreating} /> : null}
    </div>
  );
}
