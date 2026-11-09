import { Loader2, MonitorPlay, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { DialogContent } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Switch } from "@/components/ui/switch";
import { ApiError } from "@/lib/api-client";
import type { BrowserName, Project, RunCreate } from "@/types/api";

import { useExecutionRuntime, useStartRun } from "./api";
import { BROWSER_LABELS } from "./format";

const BROWSERS: BrowserName[] = ["chromium", "firefox", "webkit"];

export function RunTestDialog({
  project,
  versionId,
  versionNumber,
  testName,
}: {
  project: Project;
  versionId: string;
  versionNumber: number;
  testName: string;
}) {
  const navigate = useNavigate();
  const runtime = useExecutionRuntime();
  const start = useStartRun();
  const defaultEnv = project.environments.find((e) => e.is_default) ?? project.environments[0];
  const [environmentId, setEnvironmentId] = useState(defaultEnv?.id ?? "");
  const [browser, setBrowser] = useState<BrowserName>("chromium");
  const [screenshots, setScreenshots] = useState<RunCreate["screenshots"]>("every_step");
  const [trace, setTrace] = useState(true);
  const [video, setVideo] = useState(false);

  const browsers = runtime.data?.browsers ?? {};
  const unavailable = runtime.data && !runtime.data.available;
  const missing = start.error instanceof ApiError ? (start.error.details as { missing?: string[] } | null)?.missing : null;

  const submit = () =>
    start.mutate(
      { versionId, body: { environment_id: environmentId || null, browser, screenshots, trace, video } },
      {
        onSuccess: (execution) => {
          toast.success("Run started");
          void navigate(`/executions/${execution.id}`);
        },
      },
    );

  return (
    <DialogContent
      title="Run test"
      description={
        <>
          {testName}, version {versionNumber}
        </>
      }
      footer={
        <Button onClick={submit} disabled={start.isPending || Boolean(unavailable) || browsers[browser] === false}>
          {start.isPending ? <Loader2 className="animate-spin" /> : <MonitorPlay />} Start run
        </Button>
      }
    >
      <div className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="run-env">Environment</Label>
            <NativeSelect id="run-env" value={environmentId} onChange={(e) => setEnvironmentId(e.target.value)}>
              {project.environments.map((env) => (
                <option key={env.id} value={env.id}>
                  {env.name} — {env.effective_base_url}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="run-browser">Browser</Label>
            <NativeSelect id="run-browser" value={browser} onChange={(e) => setBrowser(e.target.value as BrowserName)}>
              {BROWSERS.map((name) => (
                <option key={name} value={name} disabled={browsers[name] === false}>
                  {BROWSER_LABELS[name]}
                  {browsers[name] === false ? " (not installed)" : ""}
                </option>
              ))}
            </NativeSelect>
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="run-shots">Screenshots</Label>
          <NativeSelect
            id="run-shots"
            value={screenshots}
            onChange={(e) => setScreenshots(e.target.value as RunCreate["screenshots"])}
          >
            <option value="every_step">After every step</option>
            <option value="on_failure">Only when a step fails</option>
            <option value="off">Off</option>
          </NativeSelect>
        </div>

        <div className="space-y-3">
          <label className="flex items-center justify-between gap-4 text-sm">
            <span>
              Playwright trace
              <span className="block text-xs text-faint">A step-by-step recording you can open in the Playwright trace viewer.</span>
            </span>
            <Switch checked={trace} onCheckedChange={setTrace} aria-label="Record a Playwright trace" />
          </label>
          <label className="flex items-center justify-between gap-4 text-sm">
            <span>
              Video
              <span className="block text-xs text-faint">A WebM recording of the whole run.</span>
            </span>
            <Switch checked={video} onCheckedChange={setVideo} aria-label="Record a video" />
          </label>
          <p className="text-xs text-faint">
            Runs that type secret values turn traces and video off automatically, because both would capture what is typed.
          </p>
        </div>

        {runtime.data && !runtime.data.isolated ? (
          <p className="flex gap-2 rounded-control border border-warning/40 bg-warning/10 px-3 py-2 text-[13px] text-warning">
            <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
            Development mode: the browser runs inside the API process, without the isolated browser-worker container.
          </p>
        ) : null}
        {unavailable ? (
          <p role="alert" className="text-[13px] text-failed">
            No browser is available{runtime.data?.detail ? `: ${runtime.data.detail}` : "."}
          </p>
        ) : null}
        {start.error ? (
          <div role="alert" className="text-[13px] text-failed">
            <p>{start.error.message}</p>
            {missing?.length ? <p className="mt-1 text-muted">Add the missing values in Environments and test data.</p> : null}
          </div>
        ) : null}
      </div>
    </DialogContent>
  );
}
