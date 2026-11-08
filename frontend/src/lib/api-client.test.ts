import { describe, expect, it } from "vitest";

import { useAuthStore } from "@/stores/auth-store";
import { errorBody, json, mockFetch, tokenResponse } from "@/test/utils";

import { ApiError, apiRequest } from "./api-client";

describe("apiRequest", () => {
  it("sends the bearer token and parses JSON", async () => {
    useAuthStore.getState().setSession(tokenResponse("token-a"));
    const fetchMock = mockFetch((url) => (url === "/api/v1/auth/me" ? json(200, { ok: true }) : undefined));

    await expect(apiRequest("/auth/me")).resolves.toEqual({ ok: true });
    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer token-a");
  });

  it("refreshes once on 401 and retries with the new token", async () => {
    useAuthStore.getState().setSession(tokenResponse("expired"));
    const fetchMock = mockFetch(
      (url) => (url === "/api/v1/auth/refresh" ? json(200, tokenResponse("fresh")) : undefined),
      (_url, init) => {
        const auth = (init?.headers as Record<string, string>).Authorization;
        return auth === "Bearer fresh" ? json(200, { ok: true }) : json(401, errorBody("auth.token_invalid", "Expired"));
      },
    );

    await expect(apiRequest("/system/status")).resolves.toEqual({ ok: true });
    expect(useAuthStore.getState().accessToken).toBe("fresh");
    const refreshCall = fetchMock.mock.calls.find(([url]) => url === "/api/v1/auth/refresh");
    expect((refreshCall?.[1]?.headers as Record<string, string>)["X-Requested-With"]).toBe("testpilot");
  });

  it("clears the session when refresh is rejected", async () => {
    useAuthStore.getState().setSession(tokenResponse("expired"));
    mockFetch(
      (url) =>
        url === "/api/v1/auth/refresh" ? json(401, errorBody("auth.refresh_invalid", "Session expired")) : undefined,
      () => json(401, errorBody("auth.token_invalid", "Expired")),
    );

    await expect(apiRequest("/system/status")).rejects.toBeInstanceOf(ApiError);
    expect(useAuthStore.getState().status).toBe("anonymous");
    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it("maps the error envelope, including retry-after details", async () => {
    mockFetch(() =>
      json(429, errorBody("rate_limited", "Too many attempts.", { retry_after_seconds: 120 })),
    );
    const error = await apiRequest("/auth/login", { method: "POST", auth: false }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("rate_limited");
    expect((error as ApiError).retryAfterSeconds).toBe(120);
    expect((error as ApiError).requestId).toBe("req-123");
  });
});
