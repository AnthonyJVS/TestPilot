import { useState } from "react";

import { PageHeader } from "@/components/common/PageHeader";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";

import { useExecutions } from "./api";
import { ExecutionsList } from "./ExecutionsList";

const STATUSES = [
  ["", "All statuses"],
  ["active", "In progress"],
  ["passed", "Passed"],
  ["failed", "Failed"],
  ["error", "Error"],
  ["cancelled", "Cancelled"],
] as const;

const KINDS = [
  ["", "Tests and workflows"],
  ["test_run", "Test runs"],
  ["workflow", "Workflows"],
] as const;

export function ExecutionsPage() {
  const [status, setStatus] = useState("");
  const [kind, setKind] = useState("");
  const active = useExecutions({ status: "active", limit: 50 });
  const running = active.data?.length ?? 0;
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Execution Center"
        description="Every test and workflow run: watch it live, replay it step by step, and inspect screenshots, console, network and AI calls."
        actions={
          running ? (
            <span className="inline-flex items-center gap-2 rounded-full border border-running/40 px-3 py-1 text-xs text-running">
              <span className="size-2 animate-pulse rounded-full bg-running" aria-hidden /> {running} in progress
            </span>
          ) : null
        }
      />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="filter-status">Status</Label>
          <NativeSelect id="filter-status" value={status} onChange={(e) => setStatus(e.target.value)} className="w-44">
            {STATUSES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="filter-kind">Type</Label>
          <NativeSelect id="filter-kind" value={kind} onChange={(e) => setKind(e.target.value)} className="w-52">
            {KINDS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>
      <ExecutionsList
        limit={100}
        status={status || undefined}
        kind={kind || undefined}
        emptyHint={status || kind ? "No runs match these filters." : "No runs yet. Run a test or a workflow to see it here."}
      />
    </div>
  );
}
