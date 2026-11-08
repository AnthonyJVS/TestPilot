import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";

import { routes } from "@/app/routes";
import { createQueryClient } from "@/lib/query-client";
import type { TokenResponse, User } from "@/types/api";

export const testUser: User = {
  id: "8d0f4a52-3a39-4f56-9c1f-2f3b8e0b9a11",
  email: "ada@example.com",
  display_name: "Ada Lovelace",
  is_active: true,
  created_at: "2026-11-01T10:00:00Z",
  last_login_at: "2026-11-08T09:00:00Z",
};

export function tokenResponse(token = "access-1"): TokenResponse {
  return {
    access_token: token,
    token_type: "bearer",
    expires_in: 900,
    expires_at: "2026-11-08T10:15:00Z",
    user: testUser,
  };
}

export function json(status: number, body: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function errorBody(code: string, message: string, details: unknown = null) {
  return { error: { code, message, request_id: "req-123", details } };
}

type Handler = (url: string, init: RequestInit | undefined) => Response | undefined;

/** Stub global fetch with an ordered list of handlers; the first one returning a Response wins. */
export function mockFetch(...handlers: Handler[]) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    for (const handler of handlers) {
      const response = handler(url, init);
      if (response) return response;
    }
    return json(404, errorBody("resource.not_found", `No mock for ${url}`));
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

export const systemStatus = {
  app_name: "TestPilot",
  version: "0.1.0",
  environment: "development",
  server_time: "2026-11-08T10:00:00Z",
  uptime_seconds: 3725,
  database: { status: "ok", latency_ms: 1.2, dialect: "postgresql", migration_revision: "0001", detail: null },
  redis: { status: "ok", latency_ms: 0.4, detail: null },
  rate_limiter_backend: "redis",
  registration_enabled: true,
};

export function renderApp(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false, refetchInterval: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router, queryClient };
}
