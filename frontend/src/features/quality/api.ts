import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { components } from "@/types/openapi";

type Schemas = components["schemas"];
export type FailureAnalysis = Schemas["FailureAnalysisOut"];
export type FailureReview = Schemas["FailureReviewOut"];
export type RepairProposal = Schemas["RepairProposalOut"];
export type DiffRow = Schemas["DiffRow"];
export type EvidenceItem = Schemas["EvidenceItem"];
export type Approval = Schemas["ApprovalOut"];

const reviewKey = (executionId: string) => ["failure-review", executionId] as const;

export function useFailureReview(executionId: string, enabled: boolean) {
  return useQuery({
    queryKey: reviewKey(executionId),
    queryFn: ({ signal }) => apiRequest<FailureReview>(`/executions/${executionId}/failure-analysis`, { signal }),
    enabled,
  });
}

function useRefresh(executionId: string) {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: reviewKey(executionId) });
    void queryClient.invalidateQueries({ queryKey: ["ai-requests"] });
  };
}

export function useAnalyseFailure(executionId: string) {
  const refresh = useRefresh(executionId);
  return useMutation({
    mutationFn: () => apiRequest<FailureAnalysis>(`/executions/${executionId}/failure-analysis`, { method: "POST" }),
    onSettled: refresh,
  });
}

export function useProposeRepair(executionId: string) {
  const refresh = useRefresh(executionId);
  return useMutation({
    mutationFn: (analysisId: string) => apiRequest<RepairProposal>(`/failure-analyses/${analysisId}/repair`, { method: "POST" }),
    onSettled: refresh,
  });
}

export function useApproveRepair(executionId: string) {
  const refresh = useRefresh(executionId);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (proposalId: string) => apiRequest<Approval>(`/repair-proposals/${proposalId}/approve`, { method: "POST" }),
    onSettled: () => {
      refresh();
      void queryClient.invalidateQueries({ queryKey: ["cases"] });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useRejectRepair(executionId: string) {
  const refresh = useRefresh(executionId);
  return useMutation({
    mutationFn: ({ proposalId, note }: { proposalId: string; note: string }) =>
      apiRequest<RepairProposal>(`/repair-proposals/${proposalId}/reject`, { method: "POST", body: { note } }),
    onSettled: refresh,
  });
}

export function useRollback(caseId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (versionId: string) => apiRequest<Schemas["RollbackOut"]>(`/versions/${versionId}/rollback`, { method: "POST" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["cases", caseId] });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

/** One-line, human description of a plan step (test data stays as references). */
export function describeStep(step: Record<string, unknown> | null | undefined): string {
  if (!step) return "";
  const locator = step.locator as { strategy?: string; role?: string | null; value?: string; nth?: number | null } | null | undefined;
  const target = locator
    ? `${locator.strategy === "role" ? `${locator.role ?? "role"}` : locator.strategy} “${locator.value}”${locator.nth != null ? ` #${locator.nth + 1}` : ""}`
    : "";
  const value = typeof step.value === "string" ? step.value : "";
  return [String(step.action), target, value ? `“${value}”` : ""].filter(Boolean).join(" · ");
}
