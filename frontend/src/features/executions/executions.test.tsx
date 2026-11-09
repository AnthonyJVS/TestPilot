import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { parseSse } from "@/lib/sse";
import { json, mockFetch, renderApp, tokenResponse } from "@/test/utils";
import type { Execution, ExecutionEvent } from "@/types/api";

const auth = (url: string) => (url === "/api/v1/auth/refresh" ? json(200, tokenResponse()) : undefined);

const execution: Execution = {
  id: "x1",
  project_id: "p1",
  kind: "test_run",
  status: "failed",
  trigger: "manual",
  error_code: "step.assertion_failed",
  error_message: 'Step 2 failed: Expected test id "greeting" to contain the text "Hello".',
  cancel_requested: false,
  created_at: "2026-11-09T10:00:00Z",
  started_at: "2026-11-09T10:00:01Z",
  finished_at: "2026-11-09T10:00:04Z",
  duration_ms: 3120,
  isolated: false,
  notes: ["Development mode: the browser runs inside the API process without container isolation."],
  capture: { screenshots: "every_step", trace: true, video: false },
  test: {
    id: "t1",
    test_case_id: "c1",
    test_version_id: "v1",
    environment_id: "e1",
    test_name: "Sign in",
    version_number: 2,
    environment_name: "default",
    base_url: "https://shop.example.com",
    browser: "chromium",
    browser_version: "140.0",
    status: "failed",
    steps_total: 3,
    steps_passed: 1,
    steps_failed: 1,
    started_at: "2026-11-09T10:00:01Z",
    finished_at: "2026-11-09T10:00:04Z",
    duration_ms: 3000,
    steps: [
      { index: 0, action: "goto", description: "Open the login page", status: "passed", started_at: null, finished_at: null, duration_ms: 420, url: "https://shop.example.com/login", error_code: null, error_message: null },
      {
        index: 1,
        action: "expect_text",
        description: "Greeting is shown",
        status: "failed",
        started_at: null,
        finished_at: null,
        duration_ms: 5010,
        url: "https://shop.example.com/login",
        error_code: "step.assertion_failed",
        error_message: 'Expected test id "greeting" to contain the text "Hello".',
      },
      { index: 2, action: "click", description: "Open the profile", status: "skipped", started_at: null, finished_at: null, duration_ms: null, url: null, error_code: null, error_message: null },
    ],
  },
  artifacts: [
    { id: "a1", kind: "screenshot", name: "step-000.jpg", content_type: "image/jpeg", size_bytes: 2048, step_index: 0, created_at: "2026-11-09T10:00:02Z" },
    { id: "a2", kind: "trace", name: "trace.zip", content_type: "application/zip", size_bytes: 330_000, step_index: null, created_at: "2026-11-09T10:00:04Z" },
  ],
};

function event(seq: number, type: string, message: string, extra: Partial<ExecutionEvent> = {}): ExecutionEvent {
  return { seq, ts: `2026-11-09T10:00:0${Math.min(seq, 9)}Z`, type, category: "browser", level: "info", node_id: null, step_index: null, message, data: {}, ...extra };
}

function sse(events: ExecutionEvent[]): Response {
  const body = events.map((e) => `id: ${e.seq}\nevent: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join("") + "event: end\ndata: {}\n\n";
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

describe("parseSse", () => {
  it("parses complete messages and keeps the partial remainder", () => {
    const { messages, rest } = parseSse("retry: 2000\n\n: keepalive\n\nid: 7\nevent: browser.console\ndata: {\"a\":\ndata: 1}\n\nid: 8\nda");
    expect(messages).toEqual([{ id: "7", event: "browser.console", data: '{"a":\n1}' }]);
    expect(rest).toBe("id: 8\nda");
  });
});

describe("Execution page", () => {
  it("shows steps, the failure, streamed events and artifacts of a run", async () => {
    const events = [
      event(1, "execution.created", "Run of Sign in v2 created", { category: "system" }),
      event(2, "browser.step.passed", "Step 1 passed in 420 ms", { step_index: 0 }),
      event(3, "browser.console", "[error] fixture error message", { level: "warning" }),
      event(4, "execution.failed", "Step 2 failed", { category: "system", level: "error" }),
    ];
    mockFetch(auth, (url) => {
      if (url === "/api/v1/executions/x1") return json(200, execution);
      if (url === "/api/v1/executions/x1/events/stream") return sse(events);
      if (url.startsWith("/api/v1/artifacts/")) return new Response(new Blob(["img"]), { status: 200 });
      return undefined;
    });
    renderApp("/executions/x1");

    expect(await screen.findByRole("heading", { name: /Sign in/ })).toBeInTheDocument();
    const steps = screen.getByRole("region", { name: /Steps/ });
    expect(within(steps).getByText("Open the login page")).toBeInTheDocument();
    expect(screen.getAllByText(/Expected test id "greeting"/).length).toBeGreaterThan(0);
    expect(screen.getByText("Skipped")).toBeInTheDocument();
    expect(screen.getByText(/Development mode/, { selector: "p" })).toBeInTheDocument();
    expect(await screen.findByText("[error] fixture error message")).toBeInTheDocument();
    expect(screen.getByText("4 events")).toBeInTheDocument();
    expect(screen.getByText("Playwright trace")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Console and network" }));
    expect(screen.queryByText("Step 1 passed in 420 ms")).not.toBeInTheDocument();
    expect(screen.getByText("[error] fixture error message")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Cancel run/ })).not.toBeInTheDocument();
  });
});
