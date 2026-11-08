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

## ADR-011 Test data and secrets as references (2026-11-08, accepted; implemented in M3/M4)

**Decision.** Plans reference `{{env.NAME}}` and `{{secret.NAME}}` from the
project environment. Only names are sent to AI providers. Values are resolved
by the orchestrator when building browser commands and are redacted from
events, logs and payload previews.
