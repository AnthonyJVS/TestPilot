/**
 * Historical replay (docs/EXECUTION_CENTER.md): every run is a persisted, ordered event log,
 * so the state at any point can be re-derived from the events up to a sequence number.
 */
import { useEffect, useMemo, useState } from "react";

import type { ExecutionEvent, ExecutionStep, NodeExecution } from "@/types/api";

export interface Frame {
  seq: number;
  ts: string;
  artifactId: string;
  url: string | null;
  stepIndex: number | null;
  nodeId: string | null;
  interim: boolean;
}

export function framesOf(events: ExecutionEvent[]): Frame[] {
  return events
    .filter((e) => e.type === "browser.frame" && typeof e.data.artifact_id === "string")
    .map((e) => ({
      seq: e.seq,
      ts: e.ts,
      artifactId: String(e.data.artifact_id),
      url: typeof e.data.url === "string" ? e.data.url : null,
      stepIndex: e.step_index,
      nodeId: e.node_id,
      interim: Boolean(e.data.interim),
    }));
}

/** The last frame at or before ``seq`` (optionally for one node or step). */
export function frameAt(frames: Frame[], seq: number, filter: { nodeId?: string | null; stepIndex?: number | null } = {}): Frame | undefined {
  let found: Frame | undefined;
  for (const frame of frames) {
    if (frame.seq > seq) break;
    if (filter.nodeId && frame.nodeId !== filter.nodeId) continue;
    if (filter.stepIndex !== undefined && filter.stepIndex !== null && frame.stepIndex !== filter.stepIndex) continue;
    found = frame;
  }
  return found;
}

const FINISHED = /^execution\.(completed|failed|cancelled)$/;

/** Step statuses of a test run as they were at ``seq``. */
export function stepStatesAt(events: ExecutionEvent[], steps: ExecutionStep[], seq: number): Map<number, ExecutionStep["status"]> {
  const states = new Map<number, ExecutionStep["status"]>(steps.map((s) => [s.index, "pending"]));
  let finished = false;
  for (const event of events) {
    if (event.seq > seq) break;
    if (FINISHED.test(event.type)) finished = true;
    if (event.step_index === null || event.node_id !== "execute_test") continue;
    if (event.type === "browser.step.started") states.set(event.step_index, "running");
    else if (event.type === "browser.step.passed") states.set(event.step_index, "passed");
    else if (event.type === "browser.step.failed") states.set(event.step_index, "failed");
  }
  if (finished) {
    for (const [index, state] of states) {
      if (state === "pending") states.set(index, "skipped");
      if (state === "running") states.set(index, "failed");
    }
  }
  return states;
}

const NODE_EVENTS: Record<string, NodeExecution["status"]> = {
  "node.started": "running",
  "node.retry_scheduled": "running",
  "node.completed": "completed",
  "node.failed": "failed",
  "node.skipped": "skipped",
  "node.cancelled": "cancelled",
};

/** Workflow node statuses as they were at ``seq``. */
export function nodeStatesAt(events: ExecutionEvent[], seq: number): Map<string, NodeExecution["status"]> {
  const states = new Map<string, NodeExecution["status"]>();
  for (const event of events) {
    if (event.seq > seq) break;
    const status = NODE_EVENTS[event.type];
    if (status && event.node_id) states.set(event.node_id, status);
  }
  return states;
}

const STOPS = /^(browser\.(frame|step\.)|node\.|execution\.)/;

/**
 * Replay cursor over the event log. ``cursor === null`` means "live": follow the latest event.
 * Playing advances through meaningful events (frames, steps, nodes) about twice per second.
 */
export function useReplay(events: ExecutionEvent[]) {
  const [cursor, setCursor] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const last = events[events.length - 1]?.seq ?? 0;
  const first = events[0]?.seq ?? 0;
  const at = cursor ?? last;
  const stops = useMemo(() => events.filter((e) => STOPS.test(e.type)).map((e) => e.seq), [events]);

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      setCursor((current) => {
        const from = current ?? first;
        const next = stops.find((s) => s > from);
        if (next === undefined) {
          setPlaying(false);
          return current;
        }
        return next;
      });
    }, 550);
    return () => window.clearInterval(timer);
  }, [playing, stops, first]);

  return {
    at,
    first,
    last,
    replaying: cursor !== null,
    playing,
    seek: (seq: number | null) => {
      setPlaying(false);
      setCursor(seq === null || seq >= last ? null : Math.max(first, seq));
    },
    play: () => {
      setCursor((current) => (current === null || current >= last ? first : current));
      setPlaying(true);
    },
    pause: () => setPlaying(false),
  };
}

export type Replay = ReturnType<typeof useReplay>;
