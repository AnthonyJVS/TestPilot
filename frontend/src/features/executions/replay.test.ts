import { describe, expect, it } from "vitest";

import type { ExecutionEvent, ExecutionStep } from "@/types/api";

import { frameAt, framesOf, nodeStatesAt, stepStatesAt } from "./replay";

let seq = 0;
function ev(type: string, extra: Partial<ExecutionEvent> = {}): ExecutionEvent {
  seq += 1;
  return { seq, ts: `2026-11-09T10:00:${String(seq).padStart(2, "0")}Z`, type, category: "browser", level: "info", node_id: null, step_index: null, message: type, data: {}, ...extra };
}

const step = (index: number): ExecutionStep => ({
  index,
  action: "click",
  description: `Step ${index + 1}`,
  status: "pending",
  started_at: null,
  finished_at: null,
  duration_ms: null,
  url: null,
  error_code: null,
  error_message: null,
});

describe("replay derivation", () => {
  seq = 0;
  const events = [
    ev("execution.started", { category: "system" }),
    ev("browser.step.started", { node_id: "execute_test", step_index: 0 }),
    ev("browser.frame", { node_id: "execute_test", step_index: 0, data: { artifact_id: "f1", interim: true, url: "https://a/1" } }),
    ev("browser.frame", { node_id: "execute_test", step_index: 0, data: { artifact_id: "f2", url: "https://a/2" } }),
    ev("browser.step.passed", { node_id: "execute_test", step_index: 0 }),
    ev("browser.step.started", { node_id: "execute_test", step_index: 1 }),
    ev("browser.step.failed", { node_id: "execute_test", step_index: 1 }),
    ev("execution.failed", { category: "system" }),
  ];
  const steps = [step(0), step(1), step(2)];

  it("re-derives step states at any point of the run", () => {
    expect([...stepStatesAt(events, steps, 2).values()]).toEqual(["running", "pending", "pending"]);
    expect([...stepStatesAt(events, steps, 6).values()]).toEqual(["passed", "running", "pending"]);
    // After the run ended, steps that never started are skipped.
    expect([...stepStatesAt(events, steps, 8).values()]).toEqual(["passed", "failed", "skipped"]);
  });

  it("finds the frame shown at a point, optionally for one step", () => {
    const frames = framesOf(events);
    expect(frames.map((f) => [f.artifactId, f.interim])).toEqual([
      ["f1", true],
      ["f2", false],
    ]);
    expect(frameAt(frames, 2)).toBeUndefined();
    expect(frameAt(frames, 3)?.artifactId).toBe("f1");
    expect(frameAt(frames, 8)?.url).toBe("https://a/2");
    expect(frameAt(frames, 8, { stepIndex: 1 })).toBeUndefined();
  });

  it("re-derives workflow node states", () => {
    seq = 100;
    const nodeEvents = [
      ev("node.started", { category: "node", node_id: "a" }),
      ev("node.retry_scheduled", { category: "node", node_id: "a" }),
      ev("node.completed", { category: "node", node_id: "a" }),
      ev("node.skipped", { category: "node", node_id: "b" }),
    ];
    expect(nodeStatesAt(nodeEvents, 102)).toEqual(new Map([["a", "running"]]));
    expect(nodeStatesAt(nodeEvents, 104)).toEqual(
      new Map([
        ["a", "completed"],
        ["b", "skipped"],
      ]),
    );
  });
});
