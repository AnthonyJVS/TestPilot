# Failure Analysis and Repair

> Status: **Implemented** (Milestone 7). Verified end to end with real Chromium and a fake AI
> provider in the test suite; live run with Gemini documented in the milestone report.

## 1. Principles

1. **Evidence is fact, AI output is hypothesis.** TestPilot collects numbered evidence (E1, E2,
   …) from the persisted run; the model may only cite it. Citations of IDs that do not exist are
   removed. The UI shows the two in separate, labelled columns.
2. **No silent changes.** A repair is a proposal. It becomes a new immutable version only when a
   person approves it, through the same validation and rendering as a manual approval.
3. **Smallest change, never a weaker test.** The repair prompt forbids deleting or weakening
   assertions to hide an application bug; the model can answer `no_test_change` instead.
4. **Same data rules as everywhere.** Evidence comes from records that were already scrubbed of
   secret values; test data stays as `{{env.*}}`/`{{secret.*}}` references; page content is
   wrapped as untrusted data.

## 2. Evidence (verified, from the run)

| Kind | Content |
| --- | --- |
| step | The failing step and its definition from the approved version |
| error | Error code, duration and message |
| page | URL at the failure |
| snapshot | Accessibility tree of the page when the step failed (`aria_snapshot`, ≤ 6,000 characters), captured by the browser worker on every failed step |
| progress | Earlier steps that passed, with durations |
| console / network / blocked | Console errors, failed requests and requests blocked by the network policy up to the failure |
| history | How earlier runs of the same version went |
| environment | Environment, base URL, browser and version |

The failing step's screenshot is attached only when the routed model has **verified** vision
support (provider metadata or a passed visual routing check).

## 3. AI analysis (`failure_analysis` task)

Output (`FailureAnalysisOutput`): summary, category (`locator_changed`, `element_missing`,
`timing`, `assertion_mismatch`, `navigation`, `network`, `test_data`, `environment`,
`application_bug`, `unknown`), up to five hypotheses with confidence and evidence IDs,
recommended action (`repair_test`, `report_bug`, `retry`, `fix_environment`,
`needs_more_information`) and an optional repair hint. Retries, fallback and request logging are
those of every AI task (ADR-013).

## 4. Repair proposals (`test_repair` task)

The model returns `verdict` and edits by 0-based step index: `replace`, `insert_after`,
`remove` (each step replaced or removed at most once). TestPilot then:

1. builds a step-level diff (`same`, `changed`, `added`, `removed`) and the candidate plan;
2. validates it against the project (allowed domains, declared test data, DSL rules);
3. stores the proposal as `proposed`, `invalid` (with issues, cannot be approved) or
   `no_change`; a newer proposal supersedes an open one for the same test.

**Approve** creates a plan revision with source `repair` and approves it (new version, code
re-rendered, audit `test.repair.approve`). It is refused if the test's current version changed
since the proposal (`repair.stale`). **Reject** records an optional reason.
**Rollback** (`POST /versions/{id}/rollback`) makes an earlier version current again; versions
never change and open proposals are superseded.

## 5. API

| Endpoint | Purpose |
| --- | --- |
| `POST /executions/{id}/failure-analysis` | Collect evidence and analyse a failed test run |
| `GET /executions/{id}/failure-analysis` | Latest analysis and its proposals |
| `POST /failure-analyses/{id}/repair` | Ask for a minimal, validated repair |
| `POST /repair-proposals/{id}/approve` / `reject` | Human decision |
| `POST /versions/{id}/rollback` | Make an earlier version current |

## 6. Workflows

The **Failure Analyzer** node takes another node's `On error` output, builds the same kind of
evidence for that node (page, accessibility tree, console, network, last screenshot with a
vision model) and outputs the analysis as JSON. Repairs stay in the test-run flow, where a
person approves them.
