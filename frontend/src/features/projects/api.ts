import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type {
  CaseSummary,
  Project,
  ProjectCreate,
  ProjectSummary,
  ProjectUpdate,
  Suite,
  TestCase,
  TestPlan,
  TestVersion,
} from "@/types/api";

export const projectKeys = {
  list: (q = "") => ["projects", "list", q] as const,
  all: ["projects"] as const,
  detail: (id: string) => ["projects", id] as const,
  suites: (id: string) => ["projects", id, "suites"] as const,
  cases: (id: string) => ["projects", id, "cases"] as const,
  case: (id: string) => ["cases", id] as const,
  version: (id: string) => ["versions", id] as const,
};

export function useProjects(query = "") {
  return useQuery({
    queryKey: projectKeys.list(query),
    queryFn: ({ signal }) =>
      apiRequest<ProjectSummary[]>(`/projects${query ? `?q=${encodeURIComponent(query)}` : ""}`, { signal }),
  });
}

export function useProject(id: string) {
  return useQuery({
    queryKey: projectKeys.detail(id),
    queryFn: ({ signal }) => apiRequest<Project>(`/projects/${id}`, { signal }),
  });
}

export function useSuites(projectId: string) {
  return useQuery({
    queryKey: projectKeys.suites(projectId),
    queryFn: ({ signal }) => apiRequest<Suite[]>(`/projects/${projectId}/suites`, { signal }),
  });
}

export function useCase(caseId: string | undefined) {
  return useQuery({
    queryKey: projectKeys.case(caseId ?? "none"),
    queryFn: ({ signal }) => apiRequest<TestCase>(`/cases/${caseId}`, { signal }),
    enabled: Boolean(caseId),
  });
}

export function useVersion(versionId: string | null | undefined) {
  return useQuery({
    queryKey: projectKeys.version(versionId ?? "none"),
    queryFn: ({ signal }) => apiRequest<TestVersion>(`/versions/${versionId}`, { signal }),
    enabled: Boolean(versionId),
    staleTime: Infinity, // versions are immutable
  });
}

function useInvalidateProject(projectId: string) {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: projectKeys.all });
    void queryClient.invalidateQueries({ queryKey: projectKeys.suites(projectId) });
  };
}

export function useCreateProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ProjectCreate) => apiRequest<Project>("/projects", { method: "POST", body }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: projectKeys.all }),
  });
}

export function useUpdateProject(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ProjectUpdate) => apiRequest<Project>(`/projects/${projectId}`, { method: "PATCH", body }),
    onSuccess: (project) => {
      queryClient.setQueryData(projectKeys.detail(projectId), project);
      void queryClient.invalidateQueries({ queryKey: ["projects", "list"] });
    },
  });
}

export function useDeleteProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string) => apiRequest<void>(`/projects/${projectId}`, { method: "DELETE" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: projectKeys.all }),
  });
}

/** Environment and variable mutations all return the updated project. */
export function useProjectMutation<T>(projectId: string, request: (vars: T) => Promise<Project>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: (project) => queryClient.setQueryData(projectKeys.detail(projectId), project),
  });
}

export function useCreateSuite(projectId: string) {
  const invalidate = useInvalidateProject(projectId);
  return useMutation({
    mutationFn: (name: string) =>
      apiRequest<Suite>(`/projects/${projectId}/suites`, { method: "POST", body: { name } }),
    onSuccess: invalidate,
  });
}

export function useCreateCase(projectId: string) {
  const invalidate = useInvalidateProject(projectId);
  return useMutation({
    mutationFn: (body: { suite_id: string; name: string; scenario?: string }) =>
      apiRequest<TestCase>(`/projects/${projectId}/cases`, { method: "POST", body }),
    onSuccess: invalidate,
  });
}

/** Case mutations return the full case; keep the cache and the suite list in sync. */
function useCaseMutation<T>(projectId: string, request: (vars: T) => Promise<TestCase>) {
  const queryClient = useQueryClient();
  const invalidate = useInvalidateProject(projectId);
  return useMutation({
    mutationFn: request,
    onSuccess: (testCase) => {
      queryClient.setQueryData(projectKeys.case(testCase.id), testCase);
      invalidate();
    },
  });
}

export function useUpdateCase(projectId: string, caseId: string) {
  return useCaseMutation(projectId, (body: { name?: string; scenario?: string; suite_id?: string }) =>
    apiRequest<TestCase>(`/cases/${caseId}`, { method: "PATCH", body }),
  );
}

export function useGeneratePlan(projectId: string, caseId: string) {
  return useCaseMutation(projectId, (environmentId: string | null) =>
    apiRequest<TestCase>(`/cases/${caseId}/plans/generate`, {
      method: "POST",
      body: { environment_id: environmentId },
    }),
  );
}

export function useSavePlan(projectId: string, caseId: string) {
  return useCaseMutation(projectId, ({ planId, plan }: { planId: string | null; plan: TestPlan }) =>
    planId
      ? apiRequest<TestCase>(`/plans/${planId}`, { method: "PUT", body: { plan } })
      : apiRequest<TestCase>(`/cases/${caseId}/plans`, { method: "POST", body: { plan } }),
  );
}

export function useApprovePlan(projectId: string, caseId: string) {
  const queryClient = useQueryClient();
  const invalidate = useInvalidateProject(projectId);
  return useMutation({
    mutationFn: (planId: string) => apiRequest<TestVersion>(`/plans/${planId}/approve`, { method: "POST" }),
    onSuccess: (version) => {
      queryClient.setQueryData(projectKeys.version(version.id), version);
      void queryClient.invalidateQueries({ queryKey: projectKeys.case(caseId) });
      invalidate();
    },
  });
}

export function useDeleteCase(projectId: string) {
  const invalidate = useInvalidateProject(projectId);
  return useMutation({
    mutationFn: (caseId: string) => apiRequest<void>(`/cases/${caseId}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

export type { CaseSummary };
