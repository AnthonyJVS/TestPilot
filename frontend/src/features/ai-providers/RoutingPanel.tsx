import { AlertTriangle, CircleAlert, CircleCheck, CircleX, Loader2, Play } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Switch } from "@/components/ui/switch";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { EffectiveRoute, Provider, Routing, RoutingUpdate, TaskCategory, TaskCheck } from "@/types/api";

import { useSaveRouting, useTaskCheck } from "./api";

type Mode = RoutingUpdate["mode"];
type CheckState = { status: "running" } | { status: "done"; result: TaskCheck } | { status: "failed"; message: string };

interface FormState {
  mode: Mode;
  defaultModelId: string;
  taskRoutes: Partial<Record<TaskCategory, string>>;
  fallbackEnabled: boolean;
  fallbackModelId: string;
  dailyLimit: string;
  storePreviews: boolean;
}

function toForm(routing: Routing): FormState {
  return {
    mode: routing.mode,
    defaultModelId: routing.default_model_id ?? "",
    taskRoutes: routing.task_routes as Partial<Record<TaskCategory, string>>,
    fallbackEnabled: routing.fallback_enabled,
    fallbackModelId: routing.fallback_model_id ?? "",
    dailyLimit: routing.daily_request_limit ? String(routing.daily_request_limit) : "",
    storePreviews: routing.store_payload_previews,
  };
}

function toUpdate(form: FormState): RoutingUpdate {
  const limit = Number.parseInt(form.dailyLimit, 10);
  return {
    mode: form.mode,
    default_model_id: form.defaultModelId || null,
    // Only real routes, in a stable order, so "unchanged" compares equal.
    task_routes: Object.fromEntries(
      Object.entries(form.taskRoutes)
        .filter(([, id]) => Boolean(id))
        .sort(([a], [b]) => a.localeCompare(b)),
    ) as RoutingUpdate["task_routes"],
    fallback_enabled: form.fallbackEnabled,
    fallback_model_id: form.fallbackModelId || null,
    daily_request_limit: Number.isFinite(limit) && limit > 0 ? limit : null,
    store_payload_previews: form.storePreviews,
  };
}

function ModelOptions({ providers }: { providers: Provider[] }) {
  return (
    <>
      {providers
        .filter((p) => p.models.length)
        .map((p) => (
          <optgroup key={p.id} label={`${p.name} (${p.provider_display_name})`}>
            {p.models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.display_name === m.model_id ? m.model_id : `${m.display_name} (${m.model_id})`}
              </option>
            ))}
          </optgroup>
        ))}
    </>
  );
}

function CheckCell({ state }: { state: CheckState | undefined }) {
  if (!state) return <span className="text-xs text-faint">Not checked</span>;
  if (state.status === "running")
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-running">
        <Loader2 className="size-3.5 animate-spin" aria-hidden /> Calling the model…
      </span>
    );
  if (state.status === "failed")
    return (
      <span className="inline-flex items-start gap-1.5 text-xs text-failed">
        <CircleX className="mt-px size-3.5 shrink-0" aria-hidden /> {state.message}
      </span>
    );
  const { result } = state;
  const Icon = result.status === "passed" ? CircleCheck : result.status === "failed" ? CircleAlert : CircleX;
  return (
    <div className="text-xs">
      <span
        className={cn(
          "inline-flex items-start gap-1.5",
          result.status === "passed" ? "text-completed" : result.status === "failed" ? "text-warning" : "text-failed",
        )}
      >
        <Icon className="mt-px size-3.5 shrink-0" aria-hidden />
        {result.status === "passed" ? "Passed" : result.status === "failed" ? "Wrong answer" : "Error"}: {result.message}
      </span>
      {result.status !== "error" ? (
        <p className="mt-0.5 text-faint">
          {result.actual_model ?? result.model}
          {result.latency_ms != null ? `, ${(result.latency_ms / 1000).toFixed(1)} s` : ""}
          {result.total_tokens != null ? `, ${result.total_tokens} tokens` : ""}
        </p>
      ) : null}
    </div>
  );
}

function RouteRow({
  route,
  check,
  canCheck,
  onCheck,
}: {
  route: EffectiveRoute;
  check: CheckState | undefined;
  canCheck: boolean;
  onCheck: () => void;
}) {
  return (
    <tr className="align-top">
      <th scope="row" className="py-3 pr-4 text-left font-medium">
        {route.label}
        {route.required_capabilities.includes("vision") ? (
          <span className="block text-xs font-normal text-faint">Needs image input</span>
        ) : null}
      </th>
      <td className="py-3 pr-4">
        {route.model ? (
          <>
            <p className="font-mono text-[13px]">{route.model.model_id}</p>
            <p className="text-xs text-faint">
              {route.model.provider_name}
              {route.source === "task_route" ? ", task route" : ", default"}
              {route.model.data_location === "external" ? ", external" : ", local"}
            </p>
          </>
        ) : (
          <span className="text-sm text-muted">No model selected</span>
        )}
        {route.issues.map((issue) => (
          <p key={issue} className="mt-1 flex items-start gap-1 text-xs text-failed">
            <CircleX className="mt-px size-3 shrink-0" aria-hidden /> {issue}
          </p>
        ))}
        {route.warnings.map((warning) => (
          <p key={warning} className="mt-1 flex items-start gap-1 text-xs text-warning">
            <AlertTriangle className="mt-px size-3 shrink-0" aria-hidden /> {warning}
          </p>
        ))}
      </td>
      <td className="py-3 pr-4">
        <CheckCell state={check} />
      </td>
      <td className="py-3 text-right">
        <Button
          variant="ghost"
          size="sm"
          onClick={onCheck}
          disabled={!canCheck || !route.model || route.issues.length > 0 || check?.status === "running"}
          aria-label={`Check ${route.label}`}
        >
          <Play /> Check
        </Button>
      </td>
    </tr>
  );
}

export function RoutingPanel({ routing, providers }: { routing: Routing; providers: Provider[] }) {
  const [form, setForm] = useState<FormState>(() => toForm(routing));
  const [checks, setChecks] = useState<Partial<Record<TaskCategory, CheckState>>>({});
  const [checkingAll, setCheckingAll] = useState(false);
  const save = useSaveRouting();
  const taskCheck = useTaskCheck();

  const saved = useMemo(() => JSON.stringify(toUpdate(toForm(routing))), [routing]);
  const dirty = JSON.stringify(toUpdate(form)) !== saved;
  const hasModels = providers.some((p) => p.models.length > 0);
  const update = (patch: Partial<FormState>) => setForm((f) => ({ ...f, ...patch }));

  const onSave = () =>
    save.mutate(toUpdate(form), {
      onSuccess: (next) => {
        setForm(toForm(next));
        setChecks({});
        toast.success("Routing saved");
      },
      onError: (error) => toast.error(error instanceof ApiError ? error.message : "Could not save routing."),
    });

  const runCheck = async (task: TaskCategory) => {
    setChecks((c) => ({ ...c, [task]: { status: "running" } }));
    try {
      const result = await taskCheck.mutateAsync(task);
      setChecks((c) => ({ ...c, [task]: { status: "done", result } }));
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "The check could not run.";
      setChecks((c) => ({ ...c, [task]: { status: "failed", message } }));
    }
  };

  const runAll = async () => {
    setCheckingAll(true);
    // Sequential on purpose: free-tier keys allow only a few requests per minute.
    for (const route of routing.effective) {
      if (route.model && route.issues.length === 0) await runCheck(route.task);
    }
    setCheckingAll(false);
  };

  const checkable = routing.effective.filter((r) => r.model && r.issues.length === 0).length;

  return (
    <div className="space-y-6">
      <div className="rounded-panel border border-border bg-panel p-5">
        <div role="radiogroup" aria-label="Routing mode" className="grid gap-3 md:grid-cols-2">
          {(
            [
              ["simple", "Simple", "One model handles every AI task. One key is enough."],
              ["advanced", "Advanced", "Choose a provider and model per task. Unset tasks use the default."],
            ] as const
          ).map(([value, title, text]) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={form.mode === value}
              onClick={() => update({ mode: value })}
              className={cn(
                "rounded-panel border px-4 py-3 text-left transition-colors",
                form.mode === value ? "border-beacon bg-beacon-soft" : "border-border-strong hover:bg-raised",
              )}
            >
              <span className="font-medium">{title}</span>
              <span className="mt-0.5 block text-[13px] text-muted">{text}</span>
            </button>
          ))}
        </div>

        <div className="mt-5 grid gap-5 lg:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="default-model">{form.mode === "simple" ? "Model for every task" : "Default model"}</Label>
            <NativeSelect
              id="default-model"
              value={form.defaultModelId}
              onChange={(e) => update({ defaultModelId: e.target.value })}
              disabled={!hasModels}
            >
              <option value="">{hasModels ? "Choose a model" : "Connect a provider first"}</option>
              <ModelOptions providers={providers} />
            </NativeSelect>
          </div>

          {form.mode === "advanced" ? (
            <div className="space-y-3 lg:col-span-2">
              <p className="text-[13px] font-medium text-muted">Per-task models</p>
              <div className="grid gap-3 md:grid-cols-2">
                {routing.effective.map((route) => (
                  <div key={route.task} className="space-y-1.5">
                    <Label htmlFor={`route-${route.task}`}>{route.label}</Label>
                    <NativeSelect
                      id={`route-${route.task}`}
                      value={form.taskRoutes[route.task] ?? ""}
                      onChange={(e) => update({ taskRoutes: { ...form.taskRoutes, [route.task]: e.target.value } })}
                    >
                      <option value="">Use the default model</option>
                      <ModelOptions providers={providers} />
                    </NativeSelect>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>

        <div className="mt-6 grid gap-5 border-t border-border pt-5 lg:grid-cols-2">
          <div className="space-y-3">
            <div className="flex items-start gap-3">
              <Switch
                id="fallback"
                checked={form.fallbackEnabled}
                onCheckedChange={(v) => update({ fallbackEnabled: v })}
              />
              <div>
                <Label htmlFor="fallback" className="text-text">
                  Use a fallback model
                </Label>
                <p className="text-[13px] text-muted">
                  Only when the primary model is rate-limited, out of quota or unavailable. Never for invalid keys
                  or rejected requests. Every switch is recorded. Off by default.
                </p>
              </div>
            </div>
            {form.fallbackEnabled ? (
              <NativeSelect
                aria-label="Fallback model"
                value={form.fallbackModelId}
                onChange={(e) => update({ fallbackModelId: e.target.value })}
              >
                <option value="">Choose a fallback model</option>
                <ModelOptions providers={providers} />
              </NativeSelect>
            ) : null}
          </div>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="daily-limit">Daily AI request limit</Label>
              <div className="flex items-center gap-3">
                <Input
                  id="daily-limit"
                  type="number"
                  min={1}
                  inputMode="numeric"
                  placeholder="No limit"
                  value={form.dailyLimit}
                  onChange={(e) => update({ dailyLimit: e.target.value })}
                  className="max-w-36"
                />
                <span className="text-[13px] text-muted">{routing.requests_today} used today (UTC)</span>
              </div>
              <p className="text-xs text-faint">When reached, AI work pauses until midnight UTC.</p>
            </div>
            <div className="flex items-start gap-3">
              <Switch
                id="previews"
                checked={form.storePreviews}
                onCheckedChange={(v) => update({ storePreviews: v })}
              />
              <div>
                <Label htmlFor="previews" className="text-text">
                  Keep sanitized prompt and response copies
                </Label>
                <p className="text-[13px] text-muted">
                  Secrets are redacted before storage. Turn off to keep only metadata (model, tokens, timing).
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className="mt-6 flex items-center justify-end gap-3">
          {dirty ? <span className="text-[13px] text-warning">Unsaved changes</span> : null}
          <Button onClick={onSave} disabled={!dirty || save.isPending}>
            {save.isPending ? "Saving…" : "Save routing"}
          </Button>
        </div>
      </div>

      <div className="rounded-panel border border-border bg-panel">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
          <div>
            <h3 className="text-[15px] font-semibold [font-stretch:100%]">Effective routes</h3>
            <p className="text-[13px] text-muted">
              A check makes one small real request per task and spends provider quota.
              {dirty ? " Save your changes before checking." : ""}
            </p>
          </div>
          <Button variant="secondary" size="sm" onClick={() => void runAll()} disabled={dirty || checkingAll || !checkable}>
            {checkingAll ? <Loader2 className="animate-spin" /> : <Play />}
            {checkingAll ? "Checking…" : `Check all (${checkable})`}
          </Button>
        </div>
        <div className="overflow-x-auto px-5">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-faint">
                <th scope="col" className="py-2.5 pr-4 font-medium">Task</th>
                <th scope="col" className="py-2.5 pr-4 font-medium">Model</th>
                <th scope="col" className="py-2.5 pr-4 font-medium">Check</th>
                <th scope="col" className="py-2.5 font-medium"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {routing.effective.map((route) => (
                <RouteRow
                  key={route.task}
                  route={route}
                  check={checks[route.task]}
                  canCheck={!dirty && !checkingAll}
                  onCheck={() => void runCheck(route.task)}
                />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
