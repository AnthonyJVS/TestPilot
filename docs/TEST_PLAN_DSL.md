# Test Plan DSL

> Status: **Implemented (Milestone 3)**. Source of truth:
> `backend/app/domain/test_plan.py` (schema and per-action rules),
> `backend/app/domain/plan_validation.py` (context checks) and
> `backend/app/services/test_generation/renderer.py` (code rendering).

TestPilot never executes model-generated code. AI proposes a **plan** in this
restricted format; a human reviews, edits and approves it; the approved plan is
stored as an immutable **test version**, rendered to Playwright code and (from
milestone 4) executed by a controlled adapter in an isolated browser worker.

## Plan

| Field | Meaning |
| --- | --- |
| `name`, `description` | Human-readable summary |
| `preconditions` | Facts that must hold before the test (text) |
| `test_data` | Declared variables: `{name, kind: env \| secret, description}` |
| `steps` | 1–100 ordered steps (below) |
| `expected_results`, `cleanup` | Text for reviewers and reports |

## Steps

One flat object type (portable across providers' JSON-schema subsets) with an
`action` and only the fields that action uses:

| Action | Locator | Value | Other |
| --- | --- | --- | --- |
| `goto` | — | path (`/login`) or URL on an allowed domain | |
| `click`, `check`, `uncheck` | required | — | |
| `fill`, `select_option` | required | text (may use `{{secret.X}}`) | |
| `press` | optional | key (`Enter`, `Control+A`) | |
| `wait_for` | required | — | `state`: visible/hidden/attached/detached |
| `expect_visible`, `expect_hidden` | required | — | |
| `expect_text` | required | expected text | `match`: contains/exact |
| `expect_url` | — | URL fragment | `match` |
| `expect_title` | — | title | `match` |
| `screenshot` | — | `lowercase-name` | |

Every step has a `description`; any step may set `timeout_ms` (100–120000).

**Locators**: `{strategy, value, role?, exact?, nth?}` with strategy `role`
(+ ARIA `role`, value = accessible name), `label`, `text`, `placeholder`,
`test_id`, or `css` (allowed, flagged as brittle).

## Test data

Values are never written into plans or code. Steps reference
`{{env.NAME}}` or `{{secret.NAME}}`; values live in the project environment
(secrets encrypted with AES-GCM, write-only). Secrets may only appear in
`fill`/`select_option` — never in assertions, URLs or screenshot names — and only
their **names** are ever sent to AI providers.

## Validation

Schema errors (unknown actions, missing locators, bad placeholders, extra
fields) are rejected on save. Context checks run against the project and its
default (or chosen) environment:

| Code | Severity | Rule |
| --- | --- | --- |
| `plan.domain_not_allowed` | error | `goto` URL host not in allowed domains |
| `plan.invalid_url` | error | `goto` is neither `/path` nor `https://…` |
| `plan.test_data_kind_mismatch` | error | declared `env` used as `secret` or vice versa |
| `plan.no_initial_navigation` | warning | first step is not `goto` |
| `plan.no_assertions` | warning | no `expect_*` step |
| `plan.brittle_locator` | warning | CSS locator |
| `plan.undeclared_test_data` | warning | placeholder not in `test_data` |
| `plan.variable_missing` | warning | environment has no value yet |
| `plan.secret_stored_plain` | warning | used as secret, stored as plain variable |

Errors block approval; warnings are shown to the reviewer.

## Rendering

`render(plan, base_url, version)` produces Python (`pytest-playwright`) and
TypeScript (`@playwright/test`) deterministically: same plan → same code.
Relative paths use `TESTPILOT_BASE_URL`; placeholders become `env("NAME")`
lookups. Python output is checked with `compile()`, TypeScript output with the
TypeScript compiler, in `tests/unit/test_test_plan.py`.
