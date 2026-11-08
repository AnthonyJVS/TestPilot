import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type {
  AIModel,
  AIRequestPage,
  ConnectionTest,
  Provider,
  ProviderCreate,
  ProviderType,
  Routing,
  RoutingUpdate,
  TaskCategory,
  TaskCheck,
} from "@/types/api";

const keys = {
  types: ["ai", "provider-types"] as const,
  providers: ["ai", "providers"] as const,
  routing: ["ai", "routing"] as const,
  requests: ["ai", "requests"] as const,
};

export function useProviderTypes() {
  return useQuery({
    queryKey: keys.types,
    queryFn: ({ signal }) => apiRequest<ProviderType[]>("/ai/provider-types", { signal }),
    staleTime: Infinity,
  });
}

export function useProviders() {
  return useQuery({
    queryKey: keys.providers,
    queryFn: ({ signal }) => apiRequest<Provider[]>("/ai/providers", { signal }),
  });
}

export function useRouting() {
  return useQuery({
    queryKey: keys.routing,
    queryFn: ({ signal }) => apiRequest<Routing>("/ai/routing", { signal }),
  });
}

export function useAIRequests(limit = 15) {
  return useInfiniteQuery({
    queryKey: [...keys.requests, limit],
    queryFn: ({ pageParam, signal }) => {
      const params = new URLSearchParams({ limit: String(limit) });
      if (pageParam) params.set("cursor", pageParam);
      return apiRequest<AIRequestPage>(`/ai/requests?${params.toString()}`, { signal });
    },
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
}

/** Provider changes can alter routing (deleted models) and capability evidence. */
function useInvalidateAI() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: keys.providers });
    void queryClient.invalidateQueries({ queryKey: keys.routing });
  };
}

export function useCreateProvider() {
  const invalidate = useInvalidateAI();
  return useMutation({
    mutationFn: (body: ProviderCreate) => apiRequest<Provider>("/ai/providers", { method: "POST", body }),
    onSuccess: invalidate,
  });
}

export function useDeleteProvider() {
  const invalidate = useInvalidateAI();
  return useMutation({
    mutationFn: (id: string) => apiRequest<void>(`/ai/providers/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

export function useSetCredential() {
  const invalidate = useInvalidateAI();
  return useMutation({
    mutationFn: ({ id, apiKey }: { id: string; apiKey: string }) =>
      apiRequest<Provider>(`/ai/providers/${id}/credential`, { method: "PUT", body: { api_key: apiKey } }),
    onSuccess: invalidate,
  });
}

export function useDeleteCredential() {
  const invalidate = useInvalidateAI();
  return useMutation({
    mutationFn: (id: string) => apiRequest<Provider>(`/ai/providers/${id}/credential`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

export function useTestProvider() {
  const invalidate = useInvalidateAI();
  return useMutation({
    mutationFn: (id: string) => apiRequest<ConnectionTest>(`/ai/providers/${id}/test`, { method: "POST" }),
    onSuccess: invalidate,
  });
}

export function useAddModel() {
  const invalidate = useInvalidateAI();
  return useMutation({
    mutationFn: ({ providerId, modelId }: { providerId: string; modelId: string }) =>
      apiRequest<AIModel>(`/ai/providers/${providerId}/models`, { method: "POST", body: { model_id: modelId } }),
    onSuccess: invalidate,
  });
}

export function useDeleteModel() {
  const invalidate = useInvalidateAI();
  return useMutation({
    mutationFn: (modelConfigId: string) => apiRequest<void>(`/ai/models/${modelConfigId}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

export function useSaveRouting() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RoutingUpdate) => apiRequest<Routing>("/ai/routing", { method: "PUT", body }),
    onSuccess: (routing) => queryClient.setQueryData(keys.routing, routing),
  });
}

export function useTaskCheck() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (task: TaskCategory) => apiRequest<TaskCheck>(`/ai/routing/check/${task}`, { method: "POST" }),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: keys.requests });
      void queryClient.invalidateQueries({ queryKey: keys.providers });
      void queryClient.invalidateQueries({ queryKey: keys.routing });
    },
  });
}
