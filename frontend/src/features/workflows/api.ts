import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { Execution, GraphIssue, NodeTypeDef, Workflow, WorkflowCreate, WorkflowGraph, WorkflowSummary } from "@/types/api";

export const workflowKeys = {
  all: ["workflows"] as const,
  list: (projectId?: string) => ["workflows", "list", projectId ?? "all"] as const,
  detail: (id: string) => ["workflows", id] as const,
  nodeTypes: ["workflow-node-types"] as const,
};

export function useNodeTypes() {
  return useQuery({
    queryKey: workflowKeys.nodeTypes,
    queryFn: ({ signal }) => apiRequest<NodeTypeDef[]>("/workflow-node-types", { signal }),
    staleTime: Infinity,
  });
}

export function useWorkflows(projectId?: string) {
  return useQuery({
    queryKey: workflowKeys.list(projectId),
    queryFn: ({ signal }) =>
      apiRequest<WorkflowSummary[]>(`/workflows${projectId ? `?project_id=${projectId}` : ""}`, { signal }),
  });
}

export function useWorkflow(id: string) {
  return useQuery({
    queryKey: workflowKeys.detail(id),
    queryFn: ({ signal }) => apiRequest<Workflow>(`/workflows/${id}`, { signal }),
  });
}

export function useCreateWorkflow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ projectId, body }: { projectId: string; body: WorkflowCreate }) =>
      apiRequest<Workflow>(`/projects/${projectId}/workflows`, { method: "POST", body }),
    onSuccess: (workflow) => {
      queryClient.setQueryData(workflowKeys.detail(workflow.id), workflow);
      void queryClient.invalidateQueries({ queryKey: workflowKeys.all });
    },
  });
}

export function useSaveVersion(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (graph: WorkflowGraph) => apiRequest<Workflow>(`/workflows/${id}/versions`, { method: "POST", body: { graph } }),
    onSuccess: (workflow) => {
      queryClient.setQueryData(workflowKeys.detail(id), workflow);
      void queryClient.invalidateQueries({ queryKey: workflowKeys.list() });
    },
  });
}

export function validateGraph(id: string, graph: WorkflowGraph, signal?: AbortSignal) {
  return apiRequest<{ issues: GraphIssue[]; runnable: boolean }>(`/workflows/${id}/validate`, {
    method: "POST",
    body: { graph },
    signal,
  });
}

export function useRenameWorkflow(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { name?: string; description?: string }) =>
      apiRequest<Workflow>(`/workflows/${id}`, { method: "PATCH", body }),
    onSuccess: (workflow) => {
      queryClient.setQueryData(workflowKeys.detail(id), workflow);
      void queryClient.invalidateQueries({ queryKey: workflowKeys.all });
    },
  });
}

export function useDuplicateWorkflow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiRequest<Workflow>(`/workflows/${id}/duplicate`, { method: "POST" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: workflowKeys.all }),
  });
}

export function useDeleteWorkflow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiRequest<void>(`/workflows/${id}`, { method: "DELETE" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: workflowKeys.all }),
  });
}

export function useRunWorkflow(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest<Execution>(`/workflows/${id}/run`, { method: "POST", body: {} }),
    onSuccess: (execution) => {
      queryClient.setQueryData(["executions", execution.id], execution);
      void queryClient.invalidateQueries({ queryKey: ["executions"] });
      void queryClient.invalidateQueries({ queryKey: workflowKeys.list() });
    },
  });
}
