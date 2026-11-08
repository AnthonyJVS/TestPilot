# Development Roadmap

Ordering follows the brief, with one priority from the product owner:
first make the **Testing Workspace**, **Gemini Simple Mode** and
**Workflow Studio** fully work, then the **Execution Center with real
execution events and Browser Preview** — the live visual demo is the
centrepiece of the presentation.

Each milestone ends with: what was implemented, what was tested, results,
known limitations, security considerations, next milestone.

| # | Milestone | Status |
| --- | --- | --- |
| 1 | Foundation | Implemented; Docker acceptance pending a Docker host / CI run |
| 2 | Multi-LLM foundation (Gemini-first Simple Mode) | Planned |
| 3 | Testing Workspace and test generation | Planned |
| 4 | Browser execution worker + event pipeline | Planned |
| 5 | Workflow Studio + DAG engine | Planned |
| 6 | Execution Center + Browser Preview | Planned |
| 7 | Failure analysis and controlled repair | Planned |
| 8 | Remaining providers, reports, usage dashboard, CI/CD, polish | Planned |

## M1 — Foundation

- Repository layout, docs, `.env.example`, `.gitignore`.
- FastAPI backend: settings, structured logging with redaction, error
  envelope, request IDs, security headers, health/readiness checks.
- SQLAlchemy 2 + Alembic; `users`, `auth_sessions`, `audit_logs`.
- Auth: register, login, refresh (rotation + reuse detection), logout, me;
  Argon2id; login rate limiting; audit logging.
- React + TS + Vite + Tailwind + shadcn/ui shell with the 7 navigation
  sections, auth pages, protected routes, dark/light theme, dashboard with
  real system status. Unbuilt sections are clearly labelled *planned*.
- Docker Compose: postgres, redis, migrate, backend, frontend (nginx).
- Tests: pytest (unit + API), Vitest + React Testing Library.

**Acceptance:** clean Docker startup and working authentication.

## M2 — Multi-LLM foundation (Gemini first)

- Adapter contract, registry, normalised errors, model catalog with manual
  model IDs, capability checks.
- Credential encryption (AES-GCM, versioned keys), write-only key API,
  connection tests.
- **Gemini adapter first**, verified end-to-end with a real key in Simple
  Mode for every task category; then Anthropic and OpenAI.
- Advanced Mode task routing; `ai_requests` log; retry/backoff, quota pause,
  explicit fallback policy.
- AI Providers page (add, test, browse models, manual model ID, default,
  routing, rotate/delete).

**Acceptance:** one Gemini key powers all supported task categories; three
providers configurable and routable; routing verified by tests.

## M3 — Testing Workspace and test generation

- Projects, environments, variables/secrets (encrypted, write-only),
  allowed domains.
- Suites and test cases; natural-language scenario editor.
- Requirement analysis → structured `TestPlan` (action DSL) with strict
  validation; editable plan UI; approval creates an immutable test version.
- Deterministic Playwright code rendering (Python and TypeScript views).
- Shows the provider/model used for every AI operation.

**Acceptance:** create, inspect, edit and approve a valid plan and its
generated test.

## M4 — Browser execution + event pipeline

- Celery orchestrator worker; browser worker container (Playwright:
  Chromium, Firefox, WebKit) with URL policy and resource limits.
- DSL execution, screenshots, traces, optional video, console and network
  capture, artifacts, cancellation, history.
- `execution_events` persistence + SSE stream; basic run view.

**Acceptance:** a real test runs and its artifacts can be inspected.

## M5 — Workflow Studio

- Node registry with schemas; palette, canvas (XYFlow), connections with
  port-type checks, inspector forms from JSON Schema.
- Validation, save/version/duplicate, backend DAG execution with branches,
  merges, retries, timeouts, error paths, cancellation.

**Acceptance:** build and run a real workflow through the visual editor.

## M6 — Execution Center + Browser Preview

- Live canvas states, timeline with filters, node inspector (AI and browser
  details with redaction), browser preview from real frames, historical
  replay.

**Acceptance:** observe a real execution and inspect node details without a
terminal.

## M7 — Failure analysis and repair

- Evidence collection, structured AI analysis (verified evidence vs
  hypotheses), repair proposals with diffs, approval, re-run, rollback.

## M8 — Breadth and production polish

- Adapters: DeepSeek, Mistral, xAI, OpenRouter, Azure OpenAI, AWS Bedrock,
  Ollama, LM Studio (each verified or clearly marked unverified).
- HTML reports, AI usage dashboard, security tests, E2E tests, CI/CD,
  deployment guide, screenshots in README.
