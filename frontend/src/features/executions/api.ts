import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { apiRequest, fetchWithAuth } from "@/lib/api-client";
import { streamEvents } from "@/lib/sse";
import type { Execution, ExecutionEvent, ExecutionRuntime, ExecutionSummary, RunCreate } from "@/types/api";

export const executionKeys = {
  all: ["executions"] as const,
  list: (filters: { projectId?: string; caseId?: string; status?: string; kind?: string }) => ["executions", "list", filters] as const,
  detail: (id: string) => ["executions", id] as const,
  runtime: ["execution-runtime"] as const,
};

export const TERMINAL = new Set(["passed", "failed", "error", "cancelled"]);

export function useExecutionRuntime() {
  return useQuery({
    queryKey: executionKeys.runtime,
    queryFn: ({ signal }) => apiRequest<ExecutionRuntime>("/execution-runtime", { signal }),
    staleTime: 60_000,
  });
}

export function useExecutions(filters: { projectId?: string; caseId?: string; limit?: number; status?: string; kind?: string } = {}) {
  const params = new URLSearchParams();
  if (filters.projectId) params.set("project_id", filters.projectId);
  if (filters.caseId) params.set("test_case_id", filters.caseId);
  if (filters.status) params.set("status", filters.status);
  if (filters.kind) params.set("kind", filters.kind);
  if (filters.limit) params.set("limit", String(filters.limit));
  const query = params.toString();
  return useQuery({
    queryKey: executionKeys.list({ projectId: filters.projectId, caseId: filters.caseId, status: filters.status, kind: filters.kind }),
    queryFn: ({ signal }) => apiRequest<ExecutionSummary[]>(`/executions${query ? `?${query}` : ""}`, { signal }),
    // Keep history fresh while something is still running elsewhere.
    refetchInterval: (q) => (q.state.data?.some((e) => !TERMINAL.has(e.status)) ? 3000 : false),
  });
}

export function useExecution(id: string) {
  return useQuery({
    queryKey: executionKeys.detail(id),
    queryFn: ({ signal }) => apiRequest<Execution>(`/executions/${id}`, { signal }),
  });
}

export function useStartRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ versionId, body }: { versionId: string; body: RunCreate }) =>
      apiRequest<Execution>(`/versions/${versionId}/run`, { method: "POST", body }),
    onSuccess: (execution) => {
      queryClient.setQueryData(executionKeys.detail(execution.id), execution);
      void queryClient.invalidateQueries({ queryKey: executionKeys.all });
    },
  });
}

export function useCancelRun(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest<Execution>(`/executions/${id}/cancel`, { method: "POST" }),
    onSuccess: (execution) => queryClient.setQueryData(executionKeys.detail(id), execution),
  });
}

export type StreamState = "connecting" | "open" | "reconnecting" | "closed" | "error";

/**
 * Live events for one execution: replays everything persisted, then tails new events.
 * Step/status changes refresh the execution details (coalesced).
 */
export function useExecutionEvents(id: string) {
  const queryClient = useQueryClient();
  const [store, setStore] = useState<{ id: string; events: ExecutionEvent[] }>({ id, events: [] });
  const [state, setState] = useState<StreamState>("connecting");
  const refresh = useRef<number | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const seen = new Set<number>();
    const scheduleRefresh = () => {
      if (refresh.current !== null) return;
      refresh.current = window.setTimeout(() => {
        refresh.current = null;
        void queryClient.invalidateQueries({ queryKey: executionKeys.detail(id) });
      }, 250);
    };
    streamEvents(`/executions/${id}/events/stream`, {
      signal: controller.signal,
      onStateChange: (next) => setState(next),
      onMessage: (message) => {
        let event: ExecutionEvent;
        try {
          event = JSON.parse(message.data) as ExecutionEvent;
        } catch {
          return;
        }
        if (seen.has(event.seq)) return;
        seen.add(event.seq);
        setStore((current) => (current.id === id ? { id, events: [...current.events, event] } : { id, events: [event] }));
        if (/^(execution|node)\.|^browser\.(step|frame)|^artifact\./.test(event.type)) scheduleRefresh();
      },
    })
      .then(() => {
        if (!controller.signal.aborted) {
          void queryClient.invalidateQueries({ queryKey: executionKeys.detail(id) });
          void queryClient.invalidateQueries({ queryKey: executionKeys.all });
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setState("error");
      });
    return () => {
      controller.abort();
      if (refresh.current !== null) window.clearTimeout(refresh.current);
      refresh.current = null;
    };
  }, [id, queryClient]);

  return { events: store.id === id ? store.events : [], state };
}

/** Object URL for an artifact fetched with the bearer token (img tags cannot send headers). */
export function useArtifactUrl(artifactId: string | null | undefined) {
  const [result, setResult] = useState<{ id: string; url: string | null; failed: boolean } | null>(null);
  useEffect(() => {
    if (!artifactId) return;
    const controller = new AbortController();
    let url: string | null = null;
    fetchWithAuth(`/artifacts/${artifactId}/content`, { signal: controller.signal })
      .then((response) => response.blob())
      .then((blob) => {
        url = URL.createObjectURL(blob);
        setResult({ id: artifactId, url, failed: false });
      })
      .catch(() => {
        if (!controller.signal.aborted) setResult({ id: artifactId, url: null, failed: true });
      });
    return () => {
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [artifactId]);
  const current = result && result.id === artifactId ? result : null;
  return { url: current?.url ?? null, failed: current?.failed ?? false, loading: Boolean(artifactId) && !current };
}

export async function downloadArtifact(artifactId: string, filename: string): Promise<void> {
  const response = await fetchWithAuth(`/artifacts/${artifactId}/content`);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
