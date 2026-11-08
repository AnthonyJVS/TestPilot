import { KeyRound, Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useOutletContext } from "react-router";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiRequest } from "@/lib/api-client";
import { formatRelative } from "@/lib/utils";
import type { Environment, Project } from "@/types/api";

import { useProjectMutation } from "./api";

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function VariableForm({ project, environment }: { project: Project; environment: Environment }) {
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [secret, setSecret] = useState(false);
  const save = useProjectMutation(project.id, (body: { name: string; value: string; is_secret: boolean }) =>
    apiRequest<Project>(`/environments/${environment.id}/variables/${encodeURIComponent(body.name)}`, {
      method: "PUT",
      body: { value: body.value, is_secret: body.is_secret },
    }),
  );

  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate(
      { name, value, is_secret: secret },
      {
        onSuccess: () => {
          toast.success(`${name} saved${secret ? " as a secret" : ""}`);
          setName("");
          setValue("");
          setSecret(false);
        },
      },
    );
  };

  return (
    <form onSubmit={submit} className="space-y-2 border-t border-border px-5 py-4">
      <p className="text-[13px] font-medium text-muted">Add or replace a variable</p>
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label htmlFor={`var-name-${environment.id}`} className="text-xs">
            Name
          </Label>
          <Input
            id={`var-name-${environment.id}`}
            placeholder="LOGIN_EMAIL"
            value={name}
            onChange={(e) => setName(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, "_"))}
            className="h-9 w-48 font-mono text-[13px]"
            required
          />
        </div>
        <div className="min-w-48 flex-1 space-y-1">
          <Label htmlFor={`var-value-${environment.id}`} className="text-xs">
            Value
          </Label>
          <Input
            id={`var-value-${environment.id}`}
            type={secret ? "password" : "text"}
            autoComplete="off"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="h-9 text-[13px]"
            required
          />
        </div>
        <label className="flex h-9 items-center gap-2 text-[13px] text-muted">
          <input type="checkbox" checked={secret} onChange={(e) => setSecret(e.target.checked)} className="accent-[var(--beacon)]" />
          Secret
        </label>
        <Button type="submit" variant="secondary" size="sm" className="h-9" disabled={save.isPending}>
          <Plus /> Save
        </Button>
      </div>
      <p className="text-xs text-faint">
        Secrets are encrypted, never shown again, never sent to AI providers, and only usable in fill steps.
      </p>
      {save.error ? (
        <p role="alert" className="text-xs text-failed">
          {errorText(save.error, "Could not save the variable.")}
        </p>
      ) : null}
    </form>
  );
}

function EnvironmentCard({ project, environment }: { project: Project; environment: Environment }) {
  const removeVariable = useProjectMutation(project.id, (name: string) =>
    apiRequest<Project>(`/environments/${environment.id}/variables/${encodeURIComponent(name)}`, { method: "DELETE" }),
  );
  const makeDefault = useProjectMutation(project.id, () =>
    apiRequest<Project>(`/environments/${environment.id}`, { method: "PATCH", body: { is_default: true } }),
  );
  const removeEnvironment = useProjectMutation(project.id, () =>
    apiRequest<Project>(`/environments/${environment.id}`, { method: "DELETE" }),
  );

  return (
    <article aria-labelledby={`env-${environment.id}`} className="rounded-panel border border-border bg-panel">
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 py-4">
        <div>
          <h3 id={`env-${environment.id}`} className="text-[15px] font-semibold [font-stretch:100%]">
            {environment.name}
            {environment.is_default ? <span className="ml-2 text-xs font-normal text-completed">Default</span> : null}
          </h3>
          <p className="font-mono text-xs text-faint">{environment.effective_base_url}</p>
        </div>
        {!environment.is_default ? (
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={() => makeDefault.mutate(undefined)}>
              Make default
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                removeEnvironment.mutate(undefined, { onSuccess: () => toast.success(`Deleted ${environment.name}`) })
              }
            >
              Delete
            </Button>
          </div>
        ) : null}
      </div>
      {environment.variables.length ? (
        <ul className="divide-y divide-border border-t border-border">
          {environment.variables.map((variable) => (
            <li key={variable.name} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-2.5">
              <span className="w-52 font-mono text-[13px]">{variable.name}</span>
              <span className="min-w-0 flex-1 truncate text-[13px] text-muted">
                {variable.is_secret ? (
                  <span className="inline-flex items-center gap-1.5">
                    <KeyRound className="size-3.5 text-faint" aria-hidden /> Secret, set {formatRelative(variable.updated_at)}
                  </span>
                ) : (
                  variable.value
                )}
              </span>
              <Button
                variant="ghost"
                size="icon"
                className="size-8"
                aria-label={`Delete ${variable.name}`}
                onClick={() => removeVariable.mutate(variable.name)}
              >
                <Trash2 />
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="border-t border-border px-5 py-3 text-[13px] text-muted">No test data yet.</p>
      )}
      <VariableForm project={project} environment={environment} />
    </article>
  );
}

export function EnvironmentsTab() {
  const project = useOutletContext<Project>();
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const create = useProjectMutation(project.id, (body: { name: string; base_url: string | null }) =>
    apiRequest<Project>(`/projects/${project.id}/environments`, { method: "POST", body }),
  );

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate(
      { name, base_url: baseUrl.trim() || null },
      {
        onSuccess: () => {
          setName("");
          setBaseUrl("");
        },
      },
    );
  };

  return (
    <div className="max-w-4xl space-y-5">
      <p className="text-[14px] text-muted">
        Environments hold the URL and test data for each place you test, such as staging and production. Plans reference
        test data by name, so the same test runs anywhere.
      </p>
      {project.environments.map((environment) => (
        <EnvironmentCard key={environment.id} project={project} environment={environment} />
      ))}
      <form onSubmit={submit} className="flex flex-wrap items-end gap-2 rounded-panel border border-dashed border-border-strong px-5 py-4">
        <div className="space-y-1">
          <Label htmlFor="env-name" className="text-xs">
            New environment
          </Label>
          <Input id="env-name" placeholder="staging" value={name} onChange={(e) => setName(e.target.value)} className="h-9 w-40" required />
        </div>
        <div className="min-w-56 flex-1 space-y-1">
          <Label htmlFor="env-url" className="text-xs">
            URL (optional, defaults to the project URL)
          </Label>
          <Input id="env-url" type="url" placeholder="https://staging.example.com" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} className="h-9" />
        </div>
        <Button type="submit" variant="secondary" size="sm" className="h-9" disabled={create.isPending}>
          <Plus /> Add environment
        </Button>
        {create.error ? (
          <p role="alert" className="w-full text-xs text-failed">
            {errorText(create.error, "Could not add the environment.")}
          </p>
        ) : null}
      </form>
    </div>
  );
}
