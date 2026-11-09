# Execution Center

> Status: **Implemented** — event pipeline and SSE (M4), live workflow canvas (M5), live
> frames, replay and inspector (M6). §7 lists what v1 covers and what it does not.

## 1. Layout

```
┌───────────────────────────────────────────────┬──────────────────────┐
│ Workflow canvas (read-only, live node states) │ Node inspector       │
│                                               │  common / AI /       │
│                                               │  browser tabs        │
├───────────────────────────────────────────────┼──────────────────────┤
│ Live activity timeline (filters: AI, browser, │ Browser preview      │
│ errors, warnings, system)                     │ frame + step + time  │
└───────────────────────────────────────────────┴──────────────────────┘
```

## 2. Event pipeline

```mermaid
sequenceDiagram
    participant O as Orchestrator
    participant DB as PostgreSQL
    participant R as Redis pub/sub
    participant API as FastAPI (SSE)
    participant UI as Browser UI

    UI->>API: GET /executions/{id}/events/stream (Last-Event-ID: n)
    API->>R: SUBSCRIBE exec:{id}
    API->>DB: SELECT events WHERE seq > n
    API-->>UI: replay persisted events
    O->>DB: INSERT event seq=n+1
    O->>R: PUBLISH exec:{id} {seq: n+1}
    R-->>API: message
    API-->>UI: event n+1 (deduplicated by seq)
```

- Events are written to `execution_events` first (`seq` is unique per
  execution) and published afterwards. The API subscribes before replaying
  and deduplicates by `seq`, so no event is lost between replay and live tail.
- Transport is **Server-Sent Events** (one-way, built-in resume semantics).
  The SPA uses `fetch`-based SSE so the bearer token travels in a header, not
  a URL. Commands (cancel, approve) are normal REST calls.

## 3. Event schema

```json
{
  "id": "uuid", "execution_id": "uuid", "seq": 42,
  "ts": "2026-11-08T12:00:00.123Z",
  "type": "ai.request.completed",
  "category": "ai | browser | system | node",
  "level": "info | warning | error",
  "node_id": "optional", "node_execution_id": "optional",
  "message": "Provider response received from gemini/…",
  "data": { "redacted": "payload" }
}
```

Event types (initial): `execution.created`, `execution.validated`,
`execution.queued`, `execution.started`, `execution.completed`,
`execution.failed`, `execution.cancelled`, `node.queued`, `node.started`,
`node.retry_scheduled`, `node.completed`, `node.failed`, `node.skipped`,
`ai.request.started`, `ai.request.completed`, `ai.request.failed`,
`ai.fallback.applied`, `plan.validated`, `code.generated`,
`browser.worker.started`, `browser.navigation.completed`,
`browser.action.completed`, `browser.assertion.passed`,
`browser.assertion.failed`, `browser.console`, `browser.network.failed`,
`browser.frame`, `artifact.created`, `analysis.completed`,
`report.generated`.

## 4. Node inspector

- **Common:** name, type, node execution ID, status, start/end, duration,
  attempt/retry count, input/output validation results, errors, warnings.
- **AI nodes:** provider (labelled *external* or *local*), requested and
  actual model, task category, request metadata, sanitized prompt and response,
  token usage (when the provider returns it), latency, estimated cost (only
  when a dated, sourced price exists for that exact model — otherwise
  "unknown"), provider request ID, fallback/retry history.
- **Browser nodes:** engine, current URL, action/step, screenshots and
  artifacts, console messages, failed network requests, trace reference,
  duration and result.

## 5. Browser Preview

v1 (M6) uses **real screenshots, never a simulated view**:

- After every action the worker captures a screenshot (`browser.frame`
  event with step index, URL and capture timestamp).
- While an action is in progress (navigation, waits) the worker captures
  throttled frames (≤ 1 fps, JPEG) so the preview keeps moving.
- The preview shows the frame, the step being executed, the capture time and
  a "last updated Ns ago" indicator; a filmstrip allows scrubbing in
  historical runs.
- Frames are artifacts served through ownership-checked endpoints; password
  fields are masked in screenshots via Playwright's `mask` option.

Designed for later upgrade: Chromium CDP screencast frames relayed through
Redis to the SSE stream, with the same UI component. No debugging port or
remote-control interface is ever exposed to users.

## 7. What v1 implements (Milestone 6)

| Area | Implemented |
| --- | --- |
| Live frames | While a browser action runs longer than a second, the orchestrator asks the worker for a frame about once per second (`frame` RPC, JPEG quality 50, secret fields masked, no session lock). Frames are `frame` artifacts with `browser.frame` events (`interim: true`), capped at 120 per run (300 per session in the worker). Quick steps produce none. |
| Browser Preview | Shows the latest frame (live or step screenshot) with its URL, an "in progress" badge for live frames, the step or node it belongs to and its time offset. Selecting a step or node shows that one's frames. |
| Replay | The event log is the source of truth: a scrubber over `seq` re-derives step statuses (test runs) or node statuses on the canvas (workflows), the preview frame and the timeline position at any moment. Play steps through frames, steps and node transitions; a filmstrip of key frames jumps to a moment; "Back to live" follows the run again. Works the same for finished runs. |
| Inspector | Test runs: step definition from the approved version (test data shown as references), duration, page URL, frame count, console and network evidence. Workflows: Overview (status, attempts, duration, scrubbed output), Evidence, and AI (each call from `GET /ai/requests/{id}`: external-provider label, requested and actual model, latency, tokens, attempts, fallback, sanitized prompt and validated response, cost shown as not estimated). |
| Timeline | Category filters, "Problems only", text search, expandable event data, live follow, click a time to replay to it; live frames are hidden from the list (they stay in the preview). |
| Run list | Status (including "In progress") and type filters, live counter of runs in progress. |

Not in v1: CDP screencast streaming (the design upgrade path), side-by-side comparison of two
runs, sharing a replay link with people outside the account.

