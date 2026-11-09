# Engineering Decisions (ADR log)

Each entry: context → decision → consequences. Newest last.

## ADR-001 Modular monolith API + workers (2026-11-08, accepted)

**Context.** One team, one product, strong need for consistency between API,
workflow engine and data model.
**Decision.** A single FastAPI codebase with strict package boundaries
(`api` → `services` → `infrastructure`), plus background workers built from
the same codebase (orchestrator) and one separate, minimal package for the
browser worker.
**Consequences.** Simple deployment and refactoring; boundaries are enforced
by convention and review rather than network calls. The browser worker is the
only component split out, for security (ADR-005).

## ADR-002 Celery + Redis for background jobs (2026-11-08, accepted; implemented in M4)

**Context.** Runs and AI generation must not block HTTP requests. The engine
is asyncio-based.
**Decision.** Celery with Redis broker. Each task (one workflow execution or
one AI generation job) runs an asyncio event loop. Cancellation is
cooperative (Redis flag + DB status), not `revoke(terminate=True)`.
**Alternatives.** arq/Taskiq (asyncio-native, smaller communities), Dramatiq.
Celery chosen for maturity, monitoring tooling (Flower) and familiarity.
**Consequences.** Celery does not officially support Windows; workers run in
Docker (or `--pool=solo` for local debugging only).

## ADR-003 PostgreSQL as system of record; SQLite allowed for local dev and fast tests (2026-11-08, accepted)

**Context.** The development machine currently has no Docker, PostgreSQL or
Redis. Milestones must still be verifiable.
**Decision.** PostgreSQL is the only supported production database. Models
and Alembic migrations use portable SQLAlchemy types (`Uuid`, `JSON` with a
`JSONB` variant, timezone-aware UTC datetimes via a `TypeDecorator`) so the
app and test suite also run on SQLite. Redis is optional in development
(in-memory rate limiter fallback) and required when `APP_ENV=production`.
CI runs the backend tests against PostgreSQL.
**Consequences.** No PostgreSQL-only SQL in application code without a
fallback; features that genuinely need PostgreSQL (e.g. `SKIP LOCKED`) must be
documented and gated. From M4 on, Docker is required for the worker stack.

## ADR-004 Restricted action DSL instead of executing generated code (2026-11-08, accepted; implemented in M3/M4)

**Context.** The brief asks for generated Playwright tests but forbids
running unrestricted model-generated code in the main process.
**Decision.** The AI produces a `TestPlan` whose steps use a closed set of
actions (`goto`, `click`, `fill`, `select`, `check`, `press`, `wait_for`,
`expect_*`, `screenshot`) with structured locators (`role`+`name`, `label`,
`text`, `test_id`, `placeholder`, `css` as last resort). Pydantic validates it.
The browser worker interprets the DSL. Playwright code (Python
`pytest-playwright` and TypeScript `@playwright/test`) is rendered
deterministically from the DSL for review and export.
**Consequences.** What users review is exactly what runs; no code execution
risk. Expressiveness is limited to the DSL — extended deliberately, with
tests, when needed. Exported code can run in the user's own CI.

## ADR-005 Browser worker as an isolated, secret-free container (2026-11-08, accepted; implemented in M4)

**Decision.** The orchestrator sends validated commands to the browser worker
over Redis (request/response with correlation IDs, timeouts). The worker has
no DB credentials and no AI keys, runs as non-root with resource limits and a
read-only root filesystem, and enforces URL policy per request.
**Consequences.** A compromised page/browser cannot reach provider keys or the
database. Small RPC overhead per action (milliseconds).

## ADR-006 Server-Sent Events for live updates (2026-11-08, accepted; implemented in M4/M6)

**Decision.** SSE for server→client streams, REST for commands. Events are
persisted before publishing; clients resume with `Last-Event-ID`.
**Consequences.** Works through standard HTTP proxies (Nginx buffering
disabled on the stream route); bearer token sent via fetch-based SSE.

## ADR-007 Authentication: in-memory access JWT + rotating refresh cookie (2026-11-08, accepted; implemented in M1)

**Decision.** Argon2id password hashing. Login returns a 15-minute HS256
access token (kept in memory by the SPA) and sets an `HttpOnly`,
`SameSite=Strict` refresh cookie scoped to `/api/v1/auth`. Refresh tokens are
random 256-bit values stored as SHA-256 hashes in `auth_sessions`, rotated on
each use; presenting a rotated token revokes the whole family (theft
detection). Access tokens carry a session ID that is checked on each request,
so logout and revocation take effect immediately. Refresh/logout require an
`X-Requested-With` header as an extra CSRF barrier.
**Consequences.** No tokens in `localStorage`; page reloads perform a silent
refresh. One extra indexed lookup per authenticated request.

## ADR-008 Toolchain versions (2026-11-08, accepted)

- Python ≥ 3.12 (containers: 3.13; verified locally on 3.14).
- React 19, Vite 8, Tailwind CSS 4, TanStack Query 5, XYFlow 12, Zustand 5,
  Vitest 5.
- **TypeScript 5.9**, not 6.0/7.0: `openapi-typescript` 7.x declares a peer
  dependency on `typescript ^5`, and `typescript-eslint` supports `<6.1`.
  Revisit when both support newer majors.
- React Router 8 (library mode: `createBrowserRouter`, `RouterProvider`).
- All dependencies pinned to exact versions; lockfiles committed.

## ADR-009 Frontend API types generated from OpenAPI (2026-11-08, accepted)

**Decision.** `backend/scripts/export_openapi.py` writes the OpenAPI schema;
`openapi-typescript` generates `frontend/src/types/openapi.ts`. The API
client uses these types.
**Consequences.** Contract changes surface as TypeScript errors.

## ADR-010 Every run is a workflow execution (2026-11-08, accepted; implemented in M4–M6)

**Decision.** "Run Test" instantiates a built-in workflow template
(launch browser → execute test version → analyse failure on error →
report). Custom workflows and single test runs share one execution model,
event stream and Execution Center.

## ADR-012 Evidence-based model capabilities (2026-11-08, accepted; implemented in M2)

**Context.** Providers expose very different metadata: Anthropic reports image
input and structured-output support, Gemini reports neither, OpenAI reports
nothing. Assuming capabilities would mislead users.
**Decision.** Every capability is `supported`/`unsupported`/`unknown` with a
source (`provider_metadata`, `probe`, `none`). Provider metadata fills unknowns;
real successful calls (routing checks, normal tasks) record `probe` evidence,
which metadata never overrides. Unsupported blocks a route; unknown warns.
**Consequences.** A fresh Gemini model shows vision as unknown until the visual
routing check passes — honest, at the cost of one extra request.

## ADR-013 Orchestrator-owned retries, explicit fallback (2026-11-08, accepted; implemented in M2)

**Decision.** SDK retries are disabled. The orchestrator retries only
transient errors (rate limit, unavailable, timeout) up to `AI_MAX_ATTEMPTS`,
honouring `retry_after`; waits longer than `AI_MAX_RETRY_WAIT_SECONDS` are not
slept on — the task fails as *paused* with `retry_after` so the user decides.
Quota exhaustion is never retried. Fallback is off by default, applies only to
fallback-eligible errors (rate limit, quota, unavailable, timeout) and is
recorded (requested vs actual model, reason, history). Structured output gets
one repair attempt with the validation error fed back.
**Consequences.** No silent provider switches; every attempt is auditable in
`ai_requests.retry_history`.

## ADR-014 Pinned major SDK versions on httpx2 (2026-11-08, accepted)

`google-genai 3`, `anthropic 2` and `openai 3` were released after the
architect's knowledge cutoff and all moved to `httpx2`. Their APIs were
verified by introspecting the installed packages and by mock-HTTP tests that
exercise the real SDK serialisation (two assumptions were corrected that way:
Gemini's `inlineData.mime_type` and Anthropic's bearer-token header).
Upgrades must keep `tests/unit/test_ai_adapters.py` green.

## ADR-015 Flat step model instead of a discriminated union (2026-11-08, accepted; implemented in M3)

**Context.** The plan schema is sent to providers as a JSON Schema for native
structured output. Discriminated unions render as `oneOf` + `discriminator`,
which provider schema subsets support unevenly.
**Decision.** One `Step` object with an `action` enum and nullable fields;
per-action rules (required/forbidden locator, value, match, state, where
secrets may appear) are enforced by a model validator. Invalid AI output gets
one repair attempt with the validation error, then fails without storing.
**Consequences.** Works with Gemini, Claude and OpenAI schema modes; the UI
edits every step with one form. See [TEST_PLAN_DSL.md](TEST_PLAN_DSL.md).

## ADR-016 Synchronous plan generation in M3 (2026-11-08, accepted; temporary)

**Decision.** `POST /cases/{id}/plans/generate` runs the two AI calls
(requirement analysis, test planning) inside the request (bounded by the AI
timeout and retry limits) and returns the stored draft.
**Consequences.** Simple and verifiable now; a slow provider holds one HTTP
request for up to a minute. *Update (M4):* the job queue and event pipeline now
exist, but generation moves onto them in Milestone 5, as AI nodes of the
workflow engine, so it is built once instead of twice.

## ADR-011 Test data and secrets as references (2026-11-08, accepted; implemented in M3/M4)

**Decision.** Plans reference `{{env.NAME}}` and `{{secret.NAME}}` from the
project environment. Only names are sent to AI providers. Values are resolved
by the orchestrator when building browser commands and are redacted from
events, logs and payload previews.

## ADR-017 Two execution deployments, one code path (2026-11-09, accepted; implemented in M4)

**Context.** The browser must run isolated (ADR-005), but the development machine has no
Docker or Redis, and milestones must stay verifiable with real browsers.
**Decision.** The orchestrator talks to a `BrowserClient` protocol and is started by a
`JobQueue`. Production (and Docker Compose) uses `EXECUTION_MODE=celery` +
`BROWSER_TRANSPORT=redis`: a Celery worker runs the orchestrator and the `browser-worker`
container executes commands received over Redis. Development may use `inline` + `thread`:
the same orchestrator as an asyncio task and the same `BrowserEngine` on a dedicated thread
(own Proactor event loop on Windows) inside the API process. The settings validator refuses
anything but `celery` + `redis` in production; every run records whether it was isolated and
the UI labels development runs.
**Consequences.** One engine and one orchestrator are tested with real Chromium locally and
in CI; only the transport differs (covered by fakeredis tests and the CI Docker smoke run).

## ADR-018 Evidence capture versus secrets (2026-11-09, accepted; implemented in M4)

**Context.** Playwright traces and videos record typed text; screenshots show field values;
page console and error messages can echo anything.
**Decision.** Values typed from `{{secret.*}}` are flagged per step: the worker masks those
fields in every later screenshot (Playwright `mask`). Runs whose plan uses secrets switch
trace and video off (the run shows why). Everything returned by the worker is scrubbed of
secret values before it is stored or streamed. Network logs keep method, URL without query
string, status and timing only; no headers or bodies.
**Consequences.** Secret-typing runs lose traces; plain-data runs keep full evidence.

## ADR-019 Workflow graphs as immutable JSON documents (2026-11-09, accepted; implemented in M5)

**Context.** The architecture sketch listed `workflow_nodes` and `workflow_edges` tables.
**Decision.** A `workflow_versions` row stores the whole graph (nodes with config, retry
policy, timeout and position; edges between named handles) as one Pydantic-validated JSON
document. Versions are immutable; saving an unchanged graph creates no version; executions
pin `workflow_version_id`. Per-run state lives in `workflow_node_executions`.
**Consequences.** Graphs are always read and written whole, so no joins or partial updates are
needed, and a version is trivially immutable. Querying "all workflows that use node type X"
needs a JSON query — acceptable at this scale.

## ADR-020 Browser workflow nodes compile to the test-plan DSL (2026-11-09, accepted; implemented in M5)

**Decision.** Each browser node builds one `Step` of the restricted DSL from its config and
runs it through the same orchestrator code path, browser worker, network policy, secret
masking and scrubbing as approved tests. Generated plans (AI Test Planner) only run through
`Run Plan`, which validates them against the project (allowed domains, declared test data)
before the first step.
**Consequences.** One execution model and one security boundary for tests and workflows; the
Studio cannot express browser actions the DSL does not allow.

## ADR-021 Evidence first, hypotheses second; repairs as validated plan edits (2026-11-09, accepted; implemented in M7)

**Context.** An AI explanation of a failure is only useful if people can tell what was observed
from what is guessed, and an AI "fix" must not quietly change what a test checks.
**Decision.** TestPilot builds numbered evidence from the persisted run (failing step, error,
URL, accessibility snapshot captured by the worker on failure, console, network, history) and
the model must cite it; unknown citations are dropped. Repairs are edits to the restricted plan
(replace / insert_after / remove by index), diffed and validated by TestPilot, and applied only
through the normal approval path as a new version. Rollback moves the current-version pointer;
versions stay immutable. The prompt forbids weakening assertions; `no_test_change` is a valid
answer.
**Consequences.** Every repair is reviewable as a step diff and reversible; the AI cannot create
steps outside the DSL, add domains or reveal secrets. Analysis runs synchronously in the request
(like plan generation) and costs one AI call; repair costs one more.

