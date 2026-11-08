import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { AuditLogPage, SystemStatus } from "@/types/api";

export function useSystemStatus() {
  return useQuery({
    queryKey: ["system", "status"],
    queryFn: ({ signal }) => apiRequest<SystemStatus>("/system/status", { signal }),
    refetchInterval: 15_000,
  });
}

export function useAuditLogs(limit: number) {
  return useInfiniteQuery({
    queryKey: ["audit-logs", limit],
    queryFn: ({ pageParam, signal }) => {
      const params = new URLSearchParams({ limit: String(limit) });
      if (pageParam) params.set("cursor", pageParam);
      return apiRequest<AuditLogPage>(`/audit-logs?${params.toString()}`, { signal });
    },
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
}
