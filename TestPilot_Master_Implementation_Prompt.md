# TestPilot --- Master Implementation Prompt

## Multi-LLM Autonomous Web Testing Platform with Visual Workflow Studio

You are acting as a Senior Software Architect, Senior Full-Stack
Engineer, QA Automation Architect, AI Integration Engineer, and DevOps
Engineer.

Your task is to design and implement **TestPilot**, a real, usable,
portfolio-quality web application for AI-assisted autonomous web
testing.

This is not a CLI-only tool, a basic CRUD application, or a thin wrapper
around an LLM. The primary user experience must be a polished
browser-based web application with visual workflow design, live
execution monitoring, browser preview, and detailed inspection of data
flowing through the system.

Work incrementally. Inspect the repository first, propose architecture,
implement in milestones, run tests, and keep the application working
after each milestone. Do not claim functionality is complete until it
has been implemented and verified.

------------------------------------------------------------------------

# 1. Product vision

Users create testing projects, specify a target website and describe
test scenarios in natural language. TestPilot converts the description
into a structured test plan, generates Playwright tests, validates them,
executes them in an isolated browser worker, collects evidence, analyzes
failures, and produces reports.

Example user request:

> Open the website, navigate to login, sign in with the supplied test
> account, add a product to the cart, proceed to checkout, and verify
> the displayed total.

The product must provide:

-   Natural-language test authoring.
-   Editable structured test plans.
-   Playwright test generation and execution.
-   Chromium, Firefox, and WebKit support where available.
-   Isolated browser sessions.
-   Screenshots, traces, logs, and execution artifacts.
-   AI-assisted failure analysis.
-   Human-approved test repair proposals.
-   Multi-provider AI configuration.
-   Visual workflow editor inspired by n8n.
-   Real-time execution monitor.
-   Browser preview.
-   Historical execution inspection.
-   Usage and cost visibility where provider data allows it.

# 2. Mandatory web-based visual interface

The product must be operated through a web UI. A terminal may be used by
developers for setup and diagnostics, but normal users must not need a
terminal to create, configure, run, or inspect tests.

Build three primary workspaces, accessible through persistent
application navigation.

## 2.1 Testing Workspace

This is the default project workspace.

It must include:

-   Projects list and project creation.
-   Project overview and target URL.
-   Environment configuration (development, staging, and other
    user-defined environments).
-   Natural-language scenario editor.
-   Test plan preview and editor.
-   Generated test code viewer.
-   Test suite management.
-   Run Test action.
-   Recent executions and status summaries.
-   Search, filtering, empty states, loading states, and useful error
    states.

Users must be able to review and approve a test plan before execution.
Show which AI provider/model is selected for each relevant operation.

## 2.2 Workflow Studio --- n8n-style visual editor

This is a central product feature, not a decorative diagram.

Use React Flow / XYFlow (or a well-justified maintained equivalent) to
build an interactive node-based workflow canvas.

Users must be able to:

-   Add nodes from a searchable node palette.
-   Drag nodes onto the canvas.
-   Connect compatible input/output handles.
-   Move, zoom, and pan around the canvas.
-   Select nodes and edit their configuration in an inspector panel.
-   Validate the workflow.
-   Save, duplicate, and version workflows.
-   Run a workflow.
-   View execution status on each node.
-   Inspect previous workflow executions.
-   Add conditional branches and error paths.
-   Configure retry and timeout policies.

Initial node categories:

**AI nodes** - Requirement Analyzer - Test Planner - Playwright Code
Generator - Failure Analyzer - Visual Analyzer - Test Repair Proposal -
Report Generator

**Browser nodes** - Launch Browser - Navigate - Click - Fill Input -
Select Option - Wait - Screenshot - Assert - Inspect Console - Inspect
Network

**Logic nodes** - Condition - Switch - Merge - Retry - Delay - Approval
Gate

**Data nodes** - Input - Transform Data - Validate Schema - Store
Artifact - Output

Every implemented node must have: - A stable node type identifier. - A
configuration schema. - An input schema. - An output schema. -
Validation rules. - An execution implementation. - Documented error
behavior.

Do not ship decorative nodes that cannot execute. Clearly mark planned
node types as unavailable until implemented.

Support DAG execution for ordinary workflows. Define and validate
behavior for branches, retries, merges, cancellation, and failure
propagation. Prevent invalid cycles unless a specific bounded-loop
feature is deliberately designed and safely implemented.

## 2.3 Execution Center --- live monitoring

When the user clicks **Run**, show a dedicated execution view. It should
feel like a workflow automation execution inspector, not a terminal
window.

The screen must contain:

1.  **Workflow Canvas** --- the workflow graph with live node states.
2.  **Node Inspector** --- details for the selected node.
3.  **Live Activity Timeline** --- timestamped events and logs.
4.  **Browser Preview** --- a visual view of the browser session where
    technically feasible and safely isolated.

Node states: - Waiting - Queued - Running - Completed - Failed -
Skipped - Cancelled

Use clear visual status indicators and accessible labels.

The Node Inspector must show:

**Common information** - Node name and type. - Execution ID. - Status. -
Start/end timestamps. - Duration. - Retry count. - Input and output
validation results. - Errors and warnings.

**AI node details** - Provider and actual model used. - Operation/task
type. - Request metadata. - Sanitized prompt/input payload. - Sanitized
response/output payload. - Token usage when available. - Latency. -
Estimated cost only when reliable pricing information exists. - Provider
request ID when available.

**Browser node details** - Browser engine. - Current URL. - Current
action and step. - Screenshot/artifacts. - Console messages. - Network
failures. - Relevant trace references. - Duration and result.

The Live Activity Timeline should show events such as: - Execution
created. - Workflow validation completed. - Job queued. - AI request
started. - Provider response received. - Test plan validated. -
Playwright code generated. - Browser worker started. - Navigation
completed. - Assertion passed/failed. - Screenshot captured. - Failure
analysis completed. - Report generated.

Provide filters for AI operations, browser actions, errors, warnings,
and system events.

Use WebSockets or Server-Sent Events for live updates. Persist execution
events so historical executions can be inspected after refresh or
reconnect.

## 2.4 Browser Preview

Provide an embedded browser preview in the Execution Center where
feasible.

The preview should let users observe the target website during a test
run. Prefer a secure screenshot/frame streaming approach or a carefully
isolated browser-view solution. Do not expose browser debugging ports,
host access, or unrestricted remote-control interfaces to end users.

If true live streaming is too complex for the first milestone, implement
frequent screenshot updates with clear timestamps and design the
interface so streaming can be added later. Do not display a fake live
browser.

The user should be able to see which step is being executed and the
associated screenshot.

------------------------------------------------------------------------

# 3. Multi-LLM architecture --- one provider or many

This is a core product requirement.

Users may have only one free-tier API key, for example Google Gemini, or
may have several paid provider accounts. Both usage patterns must work
well.

## 3.1 Simple Mode

The user connects one provider and selects one model. That
provider/model is used for every AI operation:

-   Requirement analysis.
-   Test plan generation.
-   Playwright code generation.
-   Failure analysis.
-   Visual analysis when supported.
-   Test repair proposals.
-   Report generation.

A single Gemini API key must be sufficient to operate the complete AI
pipeline, provided the selected model supports the relevant capabilities
and the provider's quota is available.

Do not require users to configure multiple keys.

## 3.2 Advanced Mode

Allow users to configure a provider/model for each task category:

-   Requirement Analysis.
-   Test Planning.
-   Code Generation.
-   Failure Analysis.
-   Visual Analysis.
-   Test Repair.
-   Report Generation.

Example configuration:

  Task                   Provider/model
  ---------------------- ----------------
  Requirement Analysis   Claude
  Test Planning          Claude
  Code Generation        GPT
  Visual Analysis        Gemini
  Failure Analysis       Claude
  Test Repair            GPT
  Report Generation      Gemini

This is only an example. Users control their own routing.

## 3.3 Custom Workflow Mode

Advanced users can place AI nodes in Workflow Studio and configure each
node's provider/model independently. The visual workflow's explicit node
configuration takes precedence over project defaults, subject to
validation and user permissions.

## 3.4 Provider abstraction and supported integrations

Implement a provider-agnostic adapter layer with a common typed
contract.

Target providers:

-   Anthropic Claude.
-   OpenAI GPT.
-   Google Gemini.
-   DeepSeek.
-   Mistral AI.
-   xAI Grok.
-   OpenRouter.
-   Azure OpenAI.
-   AWS Bedrock.
-   Ollama.
-   LM Studio.

Use official SDKs and documented interfaces where possible. Verify
current API documentation, SDK versions, model IDs, and capabilities
during implementation. Do not invent endpoints or claim unsupported
features.

Suggested abstraction responsibilities:

-   generate()
-   generateStructured()
-   analyzeFailure()
-   generateTestPlan()
-   generateTestCode()
-   proposeRepair()
-   validateConnection()
-   listAvailableModels() where supported
-   getCapabilities()

Use typed request/response schemas. Provider-specific implementation
details must not leak into domain services.

Implement a provider registry and model catalog. Do not hardcode model
IDs throughout the application. Support manual model ID entry when model
discovery is unavailable.

Track capabilities such as: - Text input/output. - Structured output. -
Image/vision input. - Tool/function calling. - Context limits when
known.

Capability metadata must be based on verified provider/model
information. Do not assume all models support the same operations.

## 3.5 Provider settings UI

Create a dedicated AI Providers page where users can:

-   Add a provider.
-   Enter and update an API key.
-   Configure endpoint/deployment details where applicable.
-   Test connection.
-   Browse available models where supported.
-   Enter a model ID manually when needed.
-   Set a default provider/model.
-   Configure task-specific routing.
-   View connection status and last validation time.
-   Rotate or delete credentials.

Show clear provider and model information. Never expose stored API keys
after submission.

## 3.6 Free-tier and quota handling

Support free-tier users as a first-class use case.

Implement: - Rate-limit detection. - Quota exhaustion handling. -
Provider-specific retry/backoff where appropriate. - Queueing or pausing
affected work. - Clear user-facing errors. - Manual retry. - Explicit
user-authorized provider switch. - Usage tracking where available.

Do not bypass provider quotas, create multiple accounts, or silently
switch models. If the user's Gemini quota is exhausted, pause the
affected task and explain the situation. If fallback is explicitly
enabled, follow the configured fallback policy and record the actual
provider/model used.

## 3.7 Fallback policy

Fallback is optional and disabled by default unless the user enables it.

Never silently change provider/model. Do not fallback for invalid
credentials, authorization failures, or other permanent errors. Retry
transient failures only within bounded limits.

Record: - Requested provider/model. - Actual provider/model. - Reason
for fallback. - Original error. - Retry history.

------------------------------------------------------------------------

# 4. AI routing and execution transparency

Create a dedicated AI orchestration service that resolves the
provider/model for each AI task.

For every AI operation, record: - Task category. - Requested
provider/model. - Actual provider/model. - Start/end time. - Latency. -
Request ID if available. - Token usage if available. - Estimated cost
only if pricing data is reliable. - Success/failure. - Retry/fallback
details.

The Execution Center must make it clear which external provider receives
each request.

Users should be able to inspect sanitized input and output payloads.
Explain what categories of information are sent to external providers.
Provide data minimization settings.

Never expose: - API keys. - Passwords. - Cookies. - Authentication
tokens. - Sensitive environment variables. - Unredacted secrets.

Implement configurable redaction and safe logging. Do not log raw
credentials.

------------------------------------------------------------------------

# 5. Test generation and execution pipeline

## 5.1 Natural-language scenario input

Users describe a test in plain language. The AI produces a structured,
validated test plan before code generation.

A plan should include: - Name and description. - Preconditions. - Test
data references. - Ordered steps. - Expected results. - Assertions. -
Cleanup requirements where relevant.

Use Pydantic schemas and strict validation. Allow users to edit and
approve the plan.

## 5.2 Playwright code generation

Generate maintainable Playwright tests using safe, supported APIs.

Generated code must be reviewed and validated before execution. Do not
execute arbitrary model-generated shell commands or unrestricted code in
the main application process.

Prefer a restricted action/plan representation and a controlled
Playwright execution adapter. If generated Python/TypeScript test code
is executed, do so only in a strongly isolated worker with resource and
network restrictions.

## 5.3 Browser execution

Support: - Chromium. - Firefox. - WebKit.

Implement: - Isolated browser contexts. - Browser lifecycle
management. - Timeouts. - Bounded retries. - Screenshots. - Trace
artifacts. - Video recording when configured. - Console collection. -
Network error collection. - Unique execution IDs. - Cancellation. -
Execution history.

Use asynchronous job processing. API requests must not remain blocked
while a test runs.

## 5.4 Failure analysis

When a test fails, collect relevant evidence: - Failed step. - Exception
and stack trace. - Screenshot. - Browser console. - Network errors. -
Relevant trace information.

Ask the configured failure-analysis model to return a validated
structured result containing: - Failure category. - Summary. -
Evidence. - Possible causes. - Suggested fixes. - Confidence where
meaningful.

Clearly distinguish verified evidence from AI hypotheses. Never present
an AI guess as a confirmed root cause.

## 5.5 Controlled repair

AI repair must produce a proposal and diff. A user must approve the
change before it replaces the current test version. Preserve history and
allow rollback. Re-run only after approval or an explicitly configured
policy.

## 5.6 Reports

Generate HTML reports containing: - Project and execution information. -
Test suite summary. - Passed/failed/skipped tests. - Duration. -
Provider/model used for AI tasks. - Failure analysis. - Screenshots and
artifact links. - Logs and recommendations.

------------------------------------------------------------------------

# 6. Recommended technology stack

Use compatible, maintained versions and pin dependencies.

**Backend** - Python 3.12+ - FastAPI - Pydantic - SQLAlchemy 2.x -
Alembic - PostgreSQL - Redis - Celery or a well-justified asynchronous
job system - WebSockets or Server-Sent Events

**Frontend** - React - TypeScript - Vite - Tailwind CSS - shadcn/ui -
React Flow / XYFlow - TanStack Query - React Router - Zustand where
appropriate - Recharts

**Browser automation** - Playwright - pytest - pytest-playwright where
appropriate

**Infrastructure** - Docker - Docker Compose - GitHub Actions - Nginx
where appropriate

**Testing** - pytest - Vitest - React Testing Library - Playwright E2E
tests

------------------------------------------------------------------------

# 7. Backend architecture

Use modular architecture with clear boundaries.

Suggested structure:

backend/ app/ api/ routes/ dependencies/ core/ config.py security.py
logging.py domain/ entities/ interfaces/ exceptions/ services/ ai/
base.py registry.py router.py model_catalog.py providers/ workflows/
validator.py compiler.py scheduler.py executor.py test_generation/
test_execution/ failure_analysis/ test_repair/ reporting/
infrastructure/ database/ repositories/ queue/ storage/ browser/
schemas/ workers/ main.py

frontend/ src/ app/ components/ features/ dashboard/ projects/
ai-providers/ workflow-studio/ test-generator/ executions/
browser-preview/ reports/ hooks/ services/ stores/ types/ pages/

tests/ unit/ integration/ e2e/

docs/ architecture/ api/ decisions/

Improve this structure when justified. Avoid needless abstraction.

Use SOLID principles, dependency injection, adapters for external
providers, strategy pattern for provider selection, repositories where
useful, explicit domain boundaries, typed contracts, and centralized
error handling.

------------------------------------------------------------------------

# 8. Workflow engine requirements

The workflow engine must run on the backend independently of the
frontend.

Persist workflow definitions separately from execution instances.

Each execution must use an immutable snapshot of the workflow definition
and its node configuration. Editing a workflow must not alter an active
or historical execution.

Implement: - DAG validation. - Dependency resolution. - Asynchronous
node execution. - Node-level state persistence. - Input/output schema
validation. - Retry and timeout policies. - Cancellation. - Error
propagation. - Conditional branches. - Merge behavior. - Execution
recovery where safe. - Event persistence.

Define deterministic behavior for branches, retries, and failures.
Prevent invalid cycles unless a bounded loop feature is deliberately
designed and tested.

------------------------------------------------------------------------

# 9. Security requirements

Security is a first-class requirement.

Implement: - Authentication and authorization. - Secure password
hashing. - Encrypted API credentials at rest. - Backend-only provider
access. - Secret masking. - Key rotation and deletion. - Rate
limiting. - Input validation. - Audit logging. - Environment-based
configuration. - Tenant/user data isolation.

Browser worker security: - Run workers in isolated containers. - Apply
CPU, memory, time, and network limits. - Do not expose host filesystem
or Docker socket. - Restrict target domains to user-authorized
destinations. - Block localhost, private network ranges, cloud metadata
endpoints, and unauthorized internal services by default. - Validate DNS
resolution and redirects to reduce SSRF risks. - Do not permit
unrestricted shell execution. - Use a restricted browser action
interface.

Prompt injection: - Treat website content, DOM text, screenshots, and
external page content as untrusted data. - Never follow instructions
embedded in the target website. - Do not reveal secrets or system
instructions to page content. - Keep AI actions constrained to validated
tools and schemas. - Require explicit approval for sensitive or
destructive actions.

Data transparency: - Tell users what categories of information are sent
to external AI providers. - Redact secrets before storing or displaying
payloads. - Make local-model vs external-provider execution clear. - Do
not claim data is private or local if it is sent to a third-party API.

------------------------------------------------------------------------

# 10. UI/UX quality bar

The UI must look like a polished developer SaaS product, not an admin
template.

Design: - Dark theme as a polished default, with optional light theme. -
Responsive layout. - Consistent spacing and typography. - Clear
navigation. - Accessible controls. - Useful loading, empty, success, and
error states. - Functional buttons only. - No fake charts, fake logs, or
simulated execution presented as real.

Main navigation: 1. Dashboard 2. Projects 3. Workflow Studio 4.
Executions 5. AI Providers 6. Reports 7. Settings

The Workflow Studio and Execution Center must receive particular design
attention.

------------------------------------------------------------------------

# 11. Data model

Design a normalized PostgreSQL schema. Consider at minimum:

-   users
-   projects
-   project_environments
-   ai_providers
-   ai_credentials
-   ai_model_configurations
-   ai_task_routing
-   workflows
-   workflow_versions
-   workflow_nodes
-   workflow_edges
-   workflow_executions
-   workflow_node_executions
-   execution_events
-   test_suites
-   test_cases
-   test_plans
-   test_versions
-   test_executions
-   execution_steps
-   execution_artifacts
-   failure_analyses
-   repair_proposals
-   reports
-   audit_logs

Use UUIDs where appropriate, foreign keys, indexes, timestamps,
transaction boundaries, and referential integrity. Ensure strict
ownership checks for all user-owned data and artifacts.

------------------------------------------------------------------------

# 12. Observability and usage

Track: - API request duration. - Queue wait time. - Workflow duration. -
Node duration. - AI provider latency. - Provider errors. - Token usage
where available. - Browser execution duration. - Test pass/fail rates.

Build an AI Usage dashboard showing requests by provider/model/task,
token use where available, latency, error rates, and estimated costs
only when trustworthy pricing data is available.

Allow optional user-configured usage limits. When reached, pause further
AI operations and explain why. Do not invent remaining free quotas.

------------------------------------------------------------------------

# 13. Milestone-based implementation plan

Do not implement everything at once.

## Milestone 1 --- Foundation

-   Inspect repository and environment.
-   Propose architecture and risks.
-   Initialize backend and frontend.
-   Configure PostgreSQL and Redis.
-   Configure Docker Compose.
-   Implement authentication and migrations.
-   Build application shell and navigation.
-   Create initial dashboard.

Acceptance: clean Docker startup and working authentication.

## Milestone 2 --- Multi-LLM foundation

-   Provider interface and registry.
-   Integrate Anthropic, OpenAI, and Gemini first.
-   Add DeepSeek, Mistral, xAI, OpenRouter, Azure OpenAI, Bedrock,
    Ollama, and LM Studio adapters incrementally.
-   Credential encryption.
-   Connection tests.
-   Model catalog and manual model ID support.
-   Simple Mode.
-   Advanced Mode and task routing.
-   Provider management UI.

Acceptance: one Gemini key can power all supported AI task categories
where model capabilities permit; at least three independent providers
can be configured and used; task routing is verified.

## Milestone 3 --- Test generation

-   Natural-language scenario input.
-   Structured test plan.
-   Schema validation.
-   Editable plan UI.
-   Playwright code generation.
-   Versioning.

Acceptance: user can create, inspect, edit, and approve a valid test
plan and generated test.

## Milestone 4 --- Browser execution

-   Isolated workers.
-   Job queue.
-   Browser lifecycle.
-   Test execution.
-   Screenshots and traces.
-   Logs.
-   Execution history.

Acceptance: a real test can run and its artifacts can be inspected.

## Milestone 5 --- Workflow Studio

-   Node palette.
-   Canvas and connections.
-   Node configuration inspector.
-   Workflow validation.
-   Workflow persistence/versioning.
-   Backend DAG execution.
-   Node state persistence.

Acceptance: user can build and run a real workflow through the visual
editor.

## Milestone 6 --- Execution Center

-   Live node status.
-   Live activity timeline.
-   Node input/output inspector.
-   AI request/response inspection with redaction.
-   Browser Preview using real execution artifacts/streaming.
-   Historical execution replay/inspection.

Acceptance: user can observe a real execution and inspect node details
without opening a terminal.

## Milestone 7 --- Failure analysis and repair

-   Evidence collection.
-   AI failure analysis.
-   Repair proposals and diffs.
-   Human approval.
-   Re-execution.
-   Version history.

Acceptance: failed tests produce evidence-based analysis and approved
repair can be validated.

## Milestone 8 --- Reports and production polish

-   HTML reports.
-   Usage dashboard.
-   Security tests.
-   Integration and E2E tests.
-   CI/CD.
-   Documentation.
-   Deployment instructions.

Acceptance: clean deployment and end-to-end demonstration of the core
product.

------------------------------------------------------------------------

# 14. Required documentation

Create: - README.md - CONTRIBUTING.md - SECURITY.md - .env.example -
docs/ARCHITECTURE.md - docs/AI_PROVIDER_INTEGRATION.md -
docs/WORKFLOW_ENGINE.md - docs/EXECUTION_CENTER.md -
docs/DEVELOPMENT_ROADMAP.md - docs/ENGINEERING_DECISIONS.md

README must include product overview, screenshots, features, stack,
architecture diagram, installation, Docker setup, environment variables,
database setup, provider configuration, workflow usage, test generation,
execution, API docs, tests, security, and known limitations.

Use Mermaid diagrams where useful.

------------------------------------------------------------------------

# 15. Engineering rules

1.  Inspect the existing repository before changing it.
2.  Present architecture, key trade-offs, and milestone plan before
    implementation.
3.  Do not generate the whole codebase in one uncontrolled operation.
4.  Implement one milestone at a time.
5.  Run tests and verify startup after each milestone.
6.  Keep types and API contracts synchronized.
7.  Use migrations for schema changes.
8.  Never commit secrets.
9.  Never pretend an integration works without testing it.
10. Do not use mock data as if it were real execution output.
11. Clearly label unavailable or planned functionality.
12. Avoid giant files and unnecessary abstractions.
13. Keep documentation updated.
14. Record important architectural decisions.
15. Preserve working functionality while extending the project.

At the end of each milestone, report: - What was implemented. - What was
tested. - Test results. - Known limitations. - Security
considerations. - Next milestone.

# 16. First action

Start by inspecting the repository, available tools, and runtime
versions.

Then present: 1. Architecture proposal. 2. Component boundaries. 3.
Database design. 4. API contract outline. 5. Workflow execution design.
6. Security risks and mitigations. 7. Milestone implementation plan.

Do not begin large-scale coding until the architecture proposal is
clear.

Then implement Milestone 1 and verify it.

**Final objective:** TestPilot must be a genuinely usable visual AI
testing platform. A user with one Gemini API key must be able to use the
full AI workflow where supported. A user with multiple providers must be
able to route different tasks to different models. Users must be able to
visually design workflows, run them, watch real-time execution, inspect
inputs and outputs, and review browser evidence --- all through the web
interface, without relying on a console.
