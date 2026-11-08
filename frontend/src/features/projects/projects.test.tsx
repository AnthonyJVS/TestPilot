import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { json, mockFetch, renderApp, tokenResponse } from "@/test/utils";
import type { PlanRecord, Project, Suite, TestCase, TestPlan, TestVersion } from "@/types/api";

const auth = (url: string) => (url === "/api/v1/auth/refresh" ? json(200, tokenResponse()) : undefined);
const noRouting = (url: string) =>
  url === "/api/v1/ai/routing"
    ? json(200, {
        mode: "simple",
        default_model_id: null,
        task_routes: {},
        fallback_enabled: false,
        fallback_model_id: null,
        daily_request_limit: null,
        store_payload_previews: true,
        requests_today: 0,
        effective: [
          { task: "requirement_analysis", label: "Requirement analysis", source: null, model: null, required_capabilities: [], issues: ["No model selected."], warnings: [] },
          { task: "test_planning", label: "Test planning", source: null, model: null, required_capabilities: [], issues: ["No model selected."], warnings: [] },
        ],
      })
    : undefined;

const project: Project = {
  id: "p1",
  name: "Shop",
  description: "",
  base_url: "https://shop.example.com",
  allowed_domains: ["shop.example.com"],
  environments: [{ id: "e1", name: "default", base_url: null, effective_base_url: "https://shop.example.com", is_default: true, variables: [] }],
  created_at: "2026-11-08T10:00:00Z",
  updated_at: "2026-11-08T10:00:00Z",
};

const plan: TestPlan = {
  name: "Sign in",
  description: "",
  preconditions: [],
  test_data: [{ name: "LOGIN_EMAIL", kind: "env", description: "" }],
  steps: [
    { action: "goto", description: "Open the login page", locator: null, value: "/login", match: null, state: null, timeout_ms: null },
    {
      action: "fill",
      description: "Enter the email",
      locator: { strategy: "label", value: "Email", role: null, exact: false, nth: null },
      value: "{{env.LOGIN_EMAIL}}",
      match: null,
      state: null,
      timeout_ms: null,
    },
  ],
  expected_results: [],
  cleanup: [],
};

function record(overrides: Partial<PlanRecord> = {}): PlanRecord {
  return {
    id: "plan1",
    revision: 1,
    source: "ai",
    status: "draft",
    plan,
    analysis: { summary: "User signs in.", requirements: ["Login page opens"], test_data: [], ambiguities: ["Which account?"] },
    issues: [{ severity: "warning", code: "plan.no_assertions", message: "The plan has no expect_* step.", step: null }],
    environment_name: "default",
    ai_requests: [
      {
        id: "r1",
        task: "test_planning",
        status: "success",
        requested_provider_type: "gemini",
        requested_model: "gemini-test",
        actual_provider_type: "gemini",
        actual_model: "gemini-test-002",
        latency_ms: 2100,
        total_tokens: 900,
        fallback_used: false,
      },
    ],
    scenario_snapshot: "Sign in",
    created_at: "2026-11-08T10:00:00Z",
    updated_at: "2026-11-08T10:00:00Z",
    ...overrides,
  };
}

function testCase(overrides: Partial<TestCase> = {}): TestCase {
  return {
    id: "c1",
    project_id: "p1",
    suite_id: "s1",
    name: "Login works",
    scenario: "Sign in",
    status: "planned",
    current_version_id: null,
    latest_plan: record(),
    versions: [],
    created_at: "2026-11-08T10:00:00Z",
    updated_at: "2026-11-08T10:00:00Z",
    ...overrides,
  };
}

const suites: Suite[] = [
  { id: "s1", name: "General", description: "", cases: [{ id: "c1", suite_id: "s1", name: "Login works", status: "planned", current_version: null, updated_at: "2026-11-08T10:00:00Z" }] },
];

const workspace = (caseData: () => TestCase) => [
  auth,
  noRouting,
  (url: string) => (url === "/api/v1/projects/p1" ? json(200, project) : undefined),
  (url: string) => (url === "/api/v1/projects/p1/suites" ? json(200, suites) : undefined),
  (url: string, init?: RequestInit) =>
    url === "/api/v1/cases/c1" && (init?.method ?? "GET") === "GET" ? json(200, caseData()) : undefined,
];

describe("Testing Workspace", () => {
  it("creates a project from the empty state", async () => {
    const fetchMock = mockFetch(
      auth,
      (url, init) => {
        if (url === "/api/v1/projects" && init?.method === "POST") return json(201, project);
        return url.startsWith("/api/v1/projects?") || url === "/api/v1/projects" ? json(200, []) : undefined;
      },
      (url) => (url === "/api/v1/projects/p1" ? json(200, project) : undefined),
      (url) => (url === "/api/v1/projects/p1/suites" ? json(200, suites) : undefined),
    );
    const { router } = renderApp("/projects");

    await userEvent.click((await screen.findAllByRole("button", { name: /New project/ }))[0]!);
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Name"), "Shop");
    const url = within(dialog).getByLabelText("Website URL");
    await userEvent.clear(url);
    await userEvent.type(url, "https://shop.example.com");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create project" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/projects/p1"));
    const post = fetchMock.mock.calls.find(([u, i]) => u === "/api/v1/projects" && i?.method === "POST");
    expect(JSON.parse(post?.[1]?.body as string)).toMatchObject({ name: "Shop", base_url: "https://shop.example.com" });
    expect(await screen.findByRole("heading", { name: "Shop" })).toBeInTheDocument();
  });

  it("shows the AI analysis with provenance and keeps Run disabled until milestone 4", async () => {
    mockFetch(...workspace(() => testCase()));
    renderApp("/projects/p1/tests/c1");

    expect(await screen.findByRole("heading", { name: "AI analysis" })).toBeInTheDocument();
    expect(screen.getByText("Which account?")).toBeInTheDocument();
    expect(screen.getByText(/gemini-test-002/)).toBeInTheDocument();
    expect(screen.getByText(/No AI model is ready for planning/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run test/ })).toBeDisabled();
    expect(screen.getByText("The plan has no expect_* step.")).toBeInTheDocument();
    expect(screen.getByLabelText("Step 2 element")).toHaveValue("Email");
  });

  it("saves an edited step and blocks approval until saved", async () => {
    let current = testCase();
    const fetchMock = mockFetch(...workspace(() => current), (url, init) => {
      if (url !== "/api/v1/plans/plan1" || init?.method !== "PUT") return undefined;
      const body = JSON.parse(init.body as string) as { plan: TestPlan };
      current = testCase({ latest_plan: record({ source: "edited", plan: body.plan, issues: [], updated_at: "2026-11-08T11:00:00Z" }) });
      return json(200, current);
    });
    renderApp("/projects/p1/tests/c1");

    const description = await screen.findByLabelText("Step 1 description");
    await userEvent.clear(description);
    await userEvent.type(description, "Open the sign-in page");
    expect(screen.getByRole("button", { name: /Approve plan/ })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));

    await waitFor(() => expect(screen.getByRole("button", { name: /Approve plan/ })).toBeEnabled());
    const put = fetchMock.mock.calls.find(([u, i]) => u === "/api/v1/plans/plan1" && i?.method === "PUT");
    const sent = JSON.parse(put?.[1]?.body as string) as { plan: TestPlan };
    expect(sent.plan.steps[0]?.description).toBe("Open the sign-in page");
    expect(sent.plan.steps[1]?.value).toBe("{{env.LOGIN_EMAIL}}");
  });

  it("approves a plan and shows the rendered code", async () => {
    const version: TestVersion = {
      id: "v1",
      test_case_id: "c1",
      version: 1,
      plan,
      base_url: "https://shop.example.com",
      code_python: 'page.goto(BASE_URL + "/login")',
      code_typescript: 'await page.goto(BASE_URL + "/login");',
      renderer_version: "1",
      created_at: "2026-11-08T12:00:00Z",
    };
    let approved = false;
    mockFetch(
      ...workspace(() =>
        approved
          ? testCase({
              status: "approved",
              current_version_id: "v1",
              latest_plan: record({ status: "approved", issues: [] }),
              versions: [{ id: "v1", version: 1, created_at: version.created_at }],
            })
          : testCase({ latest_plan: record({ issues: [] }) }),
      ),
      (url, init) => {
        if (url === "/api/v1/plans/plan1/approve" && init?.method === "POST") {
          approved = true;
          return json(201, version);
        }
        return url === "/api/v1/versions/v1" ? json(200, version) : undefined;
      },
    );
    renderApp("/projects/p1/tests/c1");

    await userEvent.click(await screen.findByRole("button", { name: /Approve plan/ }));
    expect(await screen.findByRole("heading", { name: "Playwright code" })).toBeInTheDocument();
    expect(screen.getByLabelText(/Python code for version 1/)).toHaveTextContent('page.goto(BASE_URL + "/login")');
    await userEvent.click(screen.getByRole("tab", { name: "TypeScript" }));
    expect(screen.getByLabelText(/TypeScript code for version 1/)).toHaveTextContent("await page.goto");
  });

  it("highlights server-side validation errors on the step that caused them", async () => {
    mockFetch(
      ...workspace(() =>
        testCase({
          latest_plan: record({
            issues: [{ severity: "error", code: "plan.domain_not_allowed", message: "evil.test is not in this project's allowed domains.", step: 0 }],
          }),
        }),
      ),
    );
    renderApp("/projects/p1/tests/c1");

    expect(await screen.findByText("evil.test is not in this project's allowed domains.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Approve plan/ })).toBeDisabled();
  });
});
