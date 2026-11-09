import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { json, mockFetch, renderApp, tokenResponse } from "@/test/utils";
import type { Execution, NodeTypeDef, WorkflowGraph, WorkflowSummary } from "@/types/api";

import { compatible, fromFlow, sameGraph, toFlow } from "./graph";

const auth = (url: string) => (url === "/api/v1/auth/refresh" ? json(200, tokenResponse()) : undefined);

const port = (name: string, type: string, label = name, required = true) => ({ name, type, label, required, multi: false });
const defs: NodeTypeDef[] = [
  {
    type: "browser.launch",
    version: 1,
    category: "browser",
    label: "Launch Browser",
    description: "Opens a session.",
    available: true,
    milestone: null,
    entry: true,
    inputs: [],
    outputs: [port("session", "session", "Browser session"), port("error", "error", "On error", false)],
    config_schema: { properties: { browser: { enum: ["chromium"], type: "string", default: "chromium" } } },
    defaults: { browser: "chromium" },
  },
  {
    type: "data.output",
    version: 1,
    category: "data",
    label: "Output",
    description: "Collects the result.",
    available: true,
    milestone: null,
    entry: false,
    inputs: [port("value", "any", "Value")],
    outputs: [],
    config_schema: { properties: {} },
    defaults: {},
  },
];

const retry = { max_attempts: 1, backoff: "exponential" as const, base_seconds: 1, max_seconds: 30, retry_on: "transient" as const };
const graph: WorkflowGraph = {
  nodes: [
    { id: "launch", type: "browser.launch", label: "Launch", position: { x: 0, y: 0 }, config: { browser: "chromium" }, retry, timeout_seconds: null },
    { id: "out", type: "data.output", label: "Result", position: { x: 300.4, y: 10 }, config: {}, retry, timeout_seconds: null },
  ],
  edges: [{ id: "e1", source: "launch", source_handle: "session", target: "out", target_handle: "value" }],
};

describe("workflow graph helpers", () => {
  it("mirrors the backend port compatibility rules", () => {
    expect(compatible("session", "session")).toBe(true);
    expect(compatible("result", "any")).toBe(true);
    expect(compatible("analysis", "json")).toBe(true);
    expect(compatible("text", "session")).toBe(false);
    expect(compatible("any", "session")).toBe(false);
  });

  it("round-trips graphs through XYFlow nodes and edges", () => {
    const flow = toFlow(graph, new Map(defs.map((d) => [d.type, d])));
    expect(flow.nodes[1]?.data.def?.label).toBe("Output");
    expect(flow.edges[0]?.sourceHandle).toBe("session");
    const back = fromFlow(flow.nodes, flow.edges);
    expect(back.nodes?.[1]?.position).toEqual({ x: 300, y: 10 });
    expect(sameGraph(back, graph)).toBe(true);
  });
});

describe("Workflow pages", () => {
  it("lists workflows with their last run", async () => {
    const summary: WorkflowSummary = {
      id: "w1",
      project_id: "p1",
      project_name: "Playwright demo",
      name: "Nightly smoke",
      description: "",
      latest_version: 3,
      nodes: 5,
      updated_at: "2026-11-09T10:00:00Z",
      last_run_status: "passed",
      last_run_at: "2026-11-09T10:05:00Z",
    };
    mockFetch(auth, (url) => (url === "/api/v1/workflows" ? json(200, [summary]) : undefined));
    renderApp("/workflows");
    expect(await screen.findByText("Nightly smoke")).toBeInTheDocument();
    expect(screen.getByText(/Playwright demo · v3 · 5 nodes/)).toBeInTheDocument();
    expect(screen.getByText("Passed")).toBeInTheDocument();
  });

  it("shows node states, outputs and errors of a workflow run", async () => {
    const node = (node_id: string, label: string, status: string, extra: Record<string, unknown> = {}) => ({
      node_id,
      node_type: node_id === "launch" ? "browser.launch" : "data.output",
      label,
      status,
      attempts: 1,
      started_at: null,
      finished_at: null,
      duration_ms: 1200,
      summary: null,
      output: null,
      error_code: null,
      error_message: null,
      ...extra,
    });
    const execution = {
      id: "x2",
      project_id: "p1",
      kind: "workflow",
      status: "failed",
      trigger: "manual",
      error_code: "node.timeout",
      error_message: "Launch: Did not finish within 5 seconds.",
      cancel_requested: false,
      created_at: "2026-11-09T10:00:00Z",
      started_at: "2026-11-09T10:00:01Z",
      finished_at: "2026-11-09T10:00:07Z",
      duration_ms: 6000,
      isolated: true,
      notes: [],
      capture: {},
      test: null,
      workflow: {
        workflow_id: "w1",
        workflow_name: "Nightly smoke",
        version: 3,
        graph,
        nodes: [
          node("launch", "Launch", "failed", { error_code: "node.timeout", error_message: "Did not finish within 5 seconds.", attempts: 2 }),
          node("out", "Result", "skipped", { duration_ms: null }),
        ],
      },
      artifacts: [],
    } as unknown as Execution;
    mockFetch(auth, (url) => {
      if (url === "/api/v1/executions/x2") return json(200, execution);
      if (url === "/api/v1/workflow-node-types") return json(200, defs);
      if (url.endsWith("/events/stream")) return new Response("event: end\ndata: {}\n\n", { status: 200 });
      return undefined;
    });
    renderApp("/executions/x2");
    expect(await screen.findByRole("heading", { name: /Nightly smoke/ })).toBeInTheDocument();
    expect(screen.getByText("2/2 nodes finished")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Did not finish within 5 seconds.");
    expect(screen.getByText("Isolated browser worker")).toBeInTheDocument();
    expect(screen.getAllByText("failed").length).toBeGreaterThan(0);
    expect(screen.getByText(/2 attempts/)).toBeInTheDocument();
  });
});
