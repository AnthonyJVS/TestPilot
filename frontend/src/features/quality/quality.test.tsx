import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { json, mockFetch, renderApp, tokenResponse } from "@/test/utils";

import { describeStep, type FailureReview } from "./api";

const auth = (url: string) => (url === "/api/v1/auth/refresh" ? json(200, tokenResponse()) : undefined);

const execution = {
  id: "x9",
  project_id: "p1",
  kind: "test_run",
  status: "failed",
  trigger: "manual",
  error_code: "step.timeout",
  error_message: "Step 2 failed: Timeout 1000ms exceeded.",
  cancel_requested: false,
  created_at: "2026-11-09T10:00:00Z",
  started_at: "2026-11-09T10:00:01Z",
  finished_at: "2026-11-09T10:00:04Z",
  duration_ms: 3000,
  isolated: true,
  notes: [],
  capture: {},
  workflow: null,
  artifacts: [],
  test: {
    id: "t1",
    test_case_id: "c1",
    test_version_id: "v1",
    environment_id: "e1",
    test_name: "Sign in",
    version_number: 1,
    environment_name: "default",
    base_url: "https://shop.example.com",
    browser: "chromium",
    browser_version: "151",
    status: "failed",
    steps_total: 2,
    steps_passed: 1,
    steps_failed: 1,
    started_at: null,
    finished_at: null,
    duration_ms: 3000,
    steps: [],
  },
};

const step = (name: string) => ({ action: "click", description: name, locator: { strategy: "role", role: "button", value: name } });

const review: FailureReview = {
  analysis: {
    id: "a1",
    execution_id: "x9",
    test_case_id: "c1",
    test_version_id: "v1",
    failed_step_index: 1,
    status: "completed",
    evidence: [
      { id: "E1", kind: "step", title: "Step 2 failed: Log in", detail: "Definition: click" },
      { id: "E2", kind: "error", title: "Error step.timeout after 1000 ms", detail: "Timeout 1000ms exceeded." },
      { id: "E3", kind: "snapshot", title: "Accessibility tree", detail: '- button "Sign in"' },
    ],
    used_screenshot: false,
    result: {
      summary: "The button is now called Sign in.",
      category: "locator_changed",
      hypotheses: [{ statement: "The button was renamed.", confidence: "high", evidence_ids: ["E1", "E3"] }],
      recommended_action: "repair_test",
      repair_hint: "",
    },
    ai_request_ids: [],
    error_code: null,
    error_message: null,
    created_at: "2026-11-09T10:01:00Z",
  },
  proposals: [
    {
      id: "r1",
      analysis_id: "a1",
      test_case_id: "c1",
      base_version_id: "v1",
      status: "proposed",
      verdict: "fix_test",
      rationale: "Use the new button name.",
      diff: [
        { kind: "same", index: 0, before: { action: "goto", description: "Open", value: "/" }, after: { action: "goto", description: "Open", value: "/" }, reason: null },
        { kind: "changed", index: 1, before: step("Log in"), after: step("Sign in"), reason: "Renamed button" },
      ],
      issues: [],
      ai_request_ids: [],
      resulting_version_id: null,
      decided_at: null,
      decision_note: null,
      created_at: "2026-11-09T10:02:00Z",
    },
  ],
};

describe("describeStep", () => {
  it("describes steps on one line with test data as references", () => {
    expect(describeStep(step("Sign in"))).toBe("click · button “Sign in”");
    expect(describeStep({ action: "fill", locator: { strategy: "label", value: "Email" }, value: "{{env.EMAIL}}" })).toBe("fill · label “Email” · “{{env.EMAIL}}”");
  });
});

describe("Failure panel", () => {
  it("separates evidence from AI hypotheses and approves a repair", async () => {
    const fetchMock = mockFetch(auth, (url, init) => {
      if (url === "/api/v1/executions/x9") return json(200, execution);
      if (url === "/api/v1/executions/x9/failure-analysis") return json(200, review);
      if (url === "/api/v1/repair-proposals/r1/approve" && init?.method === "POST") {
        return json(200, { proposal: { ...review.proposals[0], status: "approved" }, version_id: "v2", version: 2 });
      }
      if (url.endsWith("/events/stream")) return new Response("event: end\ndata: {}\n\n", { status: 200 });
      return undefined;
    });
    renderApp("/executions/x9");

    const panel = await screen.findByRole("region", { name: /Why did this fail/ });
    expect(await within(panel).findByRole("heading", { name: /Verified evidence/ })).toBeInTheDocument();
    expect(within(panel).getByText("hypotheses, not facts")).toBeInTheDocument();
    expect(within(panel).getByText("The button was renamed.")).toBeInTheDocument();
    expect(within(panel).getByText("Locator changed")).toBeInTheDocument();
    const diff = within(panel).getByRole("list", { name: "Changes to the test plan" });
    expect(within(diff).getByText("click · button “Log in”")).toHaveClass("line-through");
    expect(within(diff).getByText("click · button “Sign in”")).toBeInTheDocument();

    await userEvent.click(within(panel).getByRole("button", { name: /Approve as a new version/ }));
    expect(await within(panel).findByText("Version 2 is now current.")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: /Run version 2/ })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/repair-proposals/r1/approve"))).toBe(true);
  });
});
