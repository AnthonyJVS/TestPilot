/**
 * Typed fetch wrapper for the TestPilot API.
 *
 * - Sends the in-memory access token as a bearer header.
 * - On 401, performs one silent refresh (single-flight across concurrent calls) and retries.
 * - Normalises failures into ApiError using the backend's error envelope.
 */
import { useAuthStore } from "@/stores/auth-store";
import type { ApiErrorBody, TokenResponse } from "@/types/api";

export const API_BASE = "/api/v1";
const CSRF_HEADER = { "X-Requested-With": "testpilot" } as const;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, requestId: string | null, details: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.details = details;
  }

  get retryAfterSeconds(): number | null {
    const d = this.details as { retry_after_seconds?: number } | null;
    return typeof d?.retry_after_seconds === "number" ? d.retry_after_seconds : null;
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  const body = (await response.json().catch(() => null)) as Partial<ApiErrorBody> | null;
  const err = body?.error;
  if (err && typeof err.code === "string") {
    return new ApiError(response.status, err.code, err.message, err.request_id ?? null, err.details);
  }
  const message =
    response.status >= 500
      ? "The server is unavailable. Check that the backend is running."
      : `Request failed with status ${response.status}.`;
  return new ApiError(response.status, "http_error", message, response.headers.get("x-request-id"), null);
}

function networkError(): ApiError {
  return new ApiError(0, "network_error", "Cannot reach the TestPilot server. Check your connection.", null, null);
}

let refreshInFlight: Promise<TokenResponse | null> | null = null;

/** Exchange the HttpOnly refresh cookie for a new access token. Resolves null when signed out. */
export function refreshSession(): Promise<TokenResponse | null> {
  refreshInFlight ??= (async () => {
    try {
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        credentials: "same-origin",
        headers: CSRF_HEADER,
      });
      if (!response.ok) {
        if (response.status === 401) {
          useAuthStore.getState().clearSession();
          return null;
        }
        throw await toApiError(response);
      }
      const tokens = (await response.json()) as TokenResponse;
      useAuthStore.getState().setSession(tokens);
      return tokens;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw networkError();
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  /** Attach the bearer token and refresh on 401 (default true). */
  auth?: boolean;
  csrf?: boolean;
  signal?: AbortSignal;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, auth = true, csrf = false, signal } = options;

  const send = async (): Promise<Response> => {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (csrf) Object.assign(headers, CSRF_HEADER);
    const token = useAuthStore.getState().accessToken;
    if (auth && token) headers.Authorization = `Bearer ${token}`;
    try {
      return await fetch(`${API_BASE}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        credentials: "same-origin",
        signal,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      throw networkError();
    }
  };

  let response = await send();
  if (response.status === 401 && auth) {
    const refreshed = await refreshSession();
    if (refreshed) response = await send();
  }
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
