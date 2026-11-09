import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { json, mockFetch, renderApp, tokenResponse } from "@/test/utils";
import type { Provider, ProviderType, Routing, TaskCheck } from "@/types/api";

const TASKS = [
  ["requirement_analysis", "Requirement analysis"],
  ["test_planning", "Test planning"],
  ["code_generation", "Code generation"],
  ["failure_analysis", "Failure analysis"],
  ["visual_analysis", "Visual analysis"],
  ["test_repair", "Test repair"],
  ["report_generation", "Report generation"],
] as const;

const types: ProviderType[] = [
  {
    type_id: "gemini",
    display_name: "Google Gemini",
    description: "Gemini Developer API.",
    status: "available",
    data_location: "external",
    requires_api_key: true,
    base_url_mode: "none",
    supports_model_listing: true,
    key_help_url: "https://aistudio.google.com/apikey",
    milestone: null,
    verified: true,
    default_base_url: null,
  },
  {
    type_id: "aws_bedrock",
    display_name: "AWS Bedrock",
    description: "Models in your AWS account.",
    status: "planned",
    data_location: "external",
    requires_api_key: true,
    base_url_mode: "none",
    supports_model_listing: true,
    key_help_url: null,
    milestone: null,
    verified: true,
    default_base_url: null,
  },
];

const unknown = { status: "unknown", source: "none" } as const;

const gemini: Provider = {
  id: "p1",
  provider_type: "gemini",
  provider_display_name: "Google Gemini",
  data_location: "external",
  name: "My Gemini",
  base_url: null,
  status: "connected",
  last_validated_at: "2026-11-08T10:00:00Z",
  last_error: null,
  credential: { key_hint: "WXYZ", created_at: "2026-11-08T10:00:00Z", rotated_at: null },
  models: [
    {
      id: "m1",
      provider_id: "p1",
      model_id: "gemini-test-flash",
      display_name: "Gemini Test Flash",
      source: "discovered",
      capabilities: {
        text: { status: "supported", source: "provider_metadata" },
        structured_output: unknown,
        vision: unknown,
        tool_calling: unknown,
      },
      input_token_limit: 1000000,
      output_token_limit: 65000,
      listed_by_provider: true,
    },
  ],
  created_at: "2026-11-08T10:00:00Z",
};

function routing(defaultModel: string | null): Routing {
  return {
    mode: "simple",
    default_model_id: defaultModel,
    task_routes: {},
    fallback_enabled: false,
    fallback_model_id: null,
    daily_request_limit: null,
    store_payload_previews: true,
    requests_today: 0,
    effective: TASKS.map(([task, label]) => ({
      task,
      label,
      source: defaultModel ? "default" : null,
      model: defaultModel
        ? {
            model_configuration_id: "m1",
            model_id: "gemini-test-flash",
            display_name: "Gemini Test Flash",
            provider_id: "p1",
            provider_name: "My Gemini",
            provider_type: "gemini",
            data_location: "external",
          }
        : null,
      required_capabilities: task === "visual_analysis" ? ["text", "structured_output", "vision"] : ["text", "structured_output"],
      issues: defaultModel ? [] : ["No model selected."],
      warnings: [],
    })),
  };
}

const auth = (url: string) => (url === "/api/v1/auth/refresh" ? json(200, tokenResponse()) : undefined);
const emptyRequests = (url: string) =>
  url.startsWith("/api/v1/ai/requests") ? json(200, { items: [], next_cursor: null }) : undefined;
const typesHandler = (url: string) => (url === "/api/v1/ai/provider-types" ? json(200, types) : undefined);

describe("AI Providers page", () => {
  it("guides a new user to connect a single Gemini key and tests it right away", async () => {
    let providers: Provider[] = [];
    const fetchMock = mockFetch(
      auth,
      typesHandler,
      emptyRequests,
      (url) => (url === "/api/v1/ai/routing" ? json(200, routing(null)) : undefined),
      (url, init) => {
        if (url !== "/api/v1/ai/providers") return undefined;
        if (init?.method === "POST") {
          providers = [{ ...gemini, status: "untested", models: [] }];
          return json(201, providers[0]);
        }
        return json(200, providers);
      },
      (url) => {
        if (url !== "/api/v1/ai/providers/p1/test") return undefined;
        providers = [gemini];
        return json(200, { ok: true, message: "Connected. 1 models available.", model_count: 1, provider: gemini });
      },
    );
    renderApp("/ai-providers");

    expect(await screen.findByText("Start with one key")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Connect Gemini" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Planned after v1 \(they need their own protocols\): AWS Bedrock/)).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText("API key"), "AIza-test-key-WXYZ");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save and test" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const create = fetchMock.mock.calls.find(([url, init]) => url === "/api/v1/ai/providers" && init?.method === "POST");
    expect(JSON.parse(create?.[1]?.body as string)).toEqual({
      provider_type: "gemini",
      name: "Google Gemini",
      api_key: "AIza-test-key-WXYZ",
      base_url: null,
    });
    expect(fetchMock.mock.calls.some(([url]) => url === "/api/v1/ai/providers/p1/test")).toBe(true);
    expect(await screen.findByText("Key ending WXYZ")).toBeInTheDocument();
  });

  it("shows capability evidence honestly and saves simple-mode routing", async () => {
    const fetchMock = mockFetch(
      auth,
      typesHandler,
      emptyRequests,
      (url) => (url === "/api/v1/ai/providers" ? json(200, [gemini]) : undefined),
      (url, init) => {
        if (url !== "/api/v1/ai/routing") return undefined;
        return init?.method === "PUT" ? json(200, routing("m1")) : json(200, routing(null));
      },
    );
    renderApp("/ai-providers");

    await userEvent.click(await screen.findByRole("button", { name: "1 model" }));
    const capabilities = await screen.findByRole("list", { name: "Capabilities" });
    expect(within(capabilities).getByText(/Vision/)).toHaveAttribute("title", "Vision: unknown (no evidence yet)");
    expect(within(capabilities).getByText(/Text/)).toHaveAttribute("title", "Text: supported (reported by the provider)");

    await userEvent.selectOptions(screen.getByLabelText("Model for every task"), "m1");
    await userEvent.click(screen.getByRole("button", { name: "Save routing" }));

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url, init]) => url === "/api/v1/ai/routing" && init?.method === "PUT")).toBe(true),
    );
    const put = fetchMock.mock.calls.find(([url, init]) => url === "/api/v1/ai/routing" && init?.method === "PUT");
    expect(JSON.parse(put?.[1]?.body as string)).toMatchObject({
      mode: "simple",
      default_model_id: "m1",
      fallback_enabled: false,
      daily_request_limit: null,
    });
    expect(await screen.findByRole("button", { name: "Check all (7)" })).toBeEnabled();
  });

  it("runs a routing check and shows the model that actually answered", async () => {
    const check: TaskCheck = {
      task: "visual_analysis",
      label: "Visual analysis",
      status: "passed",
      message: "Recognised the red test image.",
      provider_type: "gemini",
      model: "gemini-test-flash",
      actual_model: "gemini-test-flash-002",
      latency_ms: 1234,
      total_tokens: 321,
      ai_request_id: "r1",
    };
    mockFetch(
      auth,
      typesHandler,
      emptyRequests,
      (url) => (url === "/api/v1/ai/providers" ? json(200, [gemini]) : undefined),
      (url) => (url === "/api/v1/ai/routing" ? json(200, routing("m1")) : undefined),
      (url) => (url === "/api/v1/ai/routing/check/visual_analysis" ? json(200, check) : undefined),
    );
    renderApp("/ai-providers");

    await userEvent.click(await screen.findByRole("button", { name: "Check Visual analysis" }));
    expect(await screen.findByText(/Recognised the red test image/)).toBeInTheDocument();
    expect(screen.getByText(/gemini-test-flash-002, 1.2 s, 321 tokens/)).toBeInTheDocument();
  });
});
