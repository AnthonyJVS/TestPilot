"""Node types available in Workflow Studio (milestone 5) and the planned ones (greyed out).

Browser nodes compile their config into one step of the restricted test-plan DSL, so the same
validation (locators, value rules, where secrets may appear) and the same isolated browser
worker apply as for approved tests.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from app.domain.exceptions import AppError
from app.domain.plan_validation import has_errors, host_allowed, validate_plan
from app.domain.test_plan import PLACEHOLDER, Locator, Step, TestPlan
from app.domain.workflow import GraphIssue, GraphNode
from app.infrastructure.database.models import TestCase, TestVersion
from app.schemas.testing import RequirementAnalysis
from app.services.ai.types import TaskCategory
from app.services.test_generation import prompts
from app.services.workflows.registry import (
    EmptyConfig,
    NodeError,
    NodeResult,
    NodeRun,
    NodeType,
    PlannedNode,
    Port,
    ValidationContext,
)
from browser_worker.protocol import CaptureOptions


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


SESSION_IN = Port("session", "session", "Browser session")
SESSION_OUT = Port("session", "session", "Browser session")


def _variable_issues(
    node: GraphNode, values: Iterable[str | None], ctx: ValidationContext
) -> list[GraphIssue]:
    issues: list[GraphIssue] = []
    known = set().union(*ctx.environments.values()) if ctx.environments else set()
    for value in values:
        for match in PLACEHOLDER.finditer(value or ""):
            if match.group(2) not in known:
                issues.append(
                    GraphIssue(
                        severity="warning",
                        code="node.unknown_variable",
                        message=f"No environment defines {match.group(0)}.",
                        node_id=node.id,
                    )
                )
    return issues


# ---------------------------------------------------------------------------- data


class InputConfig(_Config):
    text: str = Field(
        default="",
        max_length=10_000,
        description="Text passed to connected nodes, e.g. a test scenario in plain language.",
        json_schema_extra={"ui": "textarea"},
    )
    data: dict[str, Any] = Field(
        default_factory=dict, description="Optional JSON object.", json_schema_extra={"ui": "json"}
    )


class InputNode(NodeType):
    type_id = "data.input"
    category = "data"
    label = "Input"
    description = "Starts the workflow with text (such as a scenario) and optional JSON data."
    config_model = InputConfig
    outputs = (Port("text", "text", "Text"), Port("data", "json", "Data"))
    entry = True
    has_error_output = False

    async def execute(self, run: NodeRun) -> NodeResult:
        config = run.config
        assert isinstance(config, InputConfig)
        return NodeResult({"text": config.text, "data": config.data}, f"{len(config.text)} chars")


class OutputNode(NodeType):
    type_id = "data.output"
    category = "data"
    label = "Output"
    description = "Collects the final result of the workflow."
    inputs = (Port("value", "any", "Value"),)
    has_error_output = False

    async def execute(self, run: NodeRun) -> NodeResult:
        return NodeResult({"value": run.inputs.get("value")}, "Result stored")


# ---------------------------------------------------------------------------- browser


class LaunchConfig(_Config):
    browser: Literal["chromium", "firefox", "webkit"] = "chromium"
    environment: str = Field(default="default", min_length=1, max_length=60)
    screenshots: Literal["every_step", "on_failure", "off"] = "every_step"
    trace: bool = True
    video: bool = False


class LaunchBrowserNode(NodeType):
    type_id = "browser.launch"
    category = "browser"
    label = "Launch Browser"
    description = "Opens a fresh, isolated browser session for an environment of the project."
    config_model = LaunchConfig
    outputs = (SESSION_OUT,)
    entry = True

    def validate_static(
        self, node: GraphNode, config: BaseModel, ctx: ValidationContext
    ) -> Iterable[GraphIssue]:
        assert isinstance(config, LaunchConfig)
        if config.environment not in ctx.environments:
            yield GraphIssue(
                severity="error",
                code="node.environment_missing",
                message=f"The project has no environment named '{config.environment}'.",
                node_id=node.id,
            )

    async def execute(self, run: NodeRun) -> NodeResult:
        config = run.config
        assert isinstance(config, LaunchConfig)
        state = await run.ctx.open_session(
            run.node.id,
            browser=config.browser,
            environment=config.environment,
            capture=CaptureOptions(
                screenshots=config.screenshots, trace=config.trace, video=config.video
            ),
        )
        await run.ctx.emit(
            "browser.worker.started",
            f"{config.browser} {state.opened.browser_version} ready for {config.environment}",
            category="browser",
            node_id=run.node.id,
            data={"browser_version": state.opened.browser_version, "session": state.ref},
        )
        return NodeResult({"session": state.handle()}, f"{config.browser} session {state.ref}")


class _StepNode(NodeType):
    """A browser node that compiles to one DSL step and passes the session on."""

    category = "browser"
    inputs = (SESSION_IN,)
    outputs = (SESSION_OUT,)

    def step(self, config: BaseModel, node: GraphNode) -> Step:  # pragma: no cover - abstract
        raise NotImplementedError

    def _compiled(self, node: GraphNode, config: BaseModel) -> Step:
        try:
            return self.step(config, node)
        except ValidationError as exc:
            message = "; ".join(e["msg"].removeprefix("Value error, ") for e in exc.errors())
            raise NodeError("node.invalid_config", message) from exc

    def validate_static(
        self, node: GraphNode, config: BaseModel, ctx: ValidationContext
    ) -> Iterable[GraphIssue]:
        try:
            step = self._compiled(node, config)
        except NodeError as exc:
            return [
                GraphIssue(
                    severity="error",
                    code="node.invalid_config",
                    message=exc.message,
                    node_id=node.id,
                )
            ]
        issues = _variable_issues(node, [step.value], ctx)
        if step.action == "goto" and step.value and step.value.startswith(("http://", "https://")):
            from urllib.parse import urlsplit

            host = urlsplit(step.value).hostname or ""
            if not host_allowed(host, ctx.allowed_domains):
                issues.append(
                    GraphIssue(
                        severity="error",
                        code="node.domain_not_allowed",
                        message=f"'{host}' is not in the project's allowed domains.",
                        node_id=node.id,
                    )
                )
        return issues

    async def execute(self, run: NodeRun) -> NodeResult:
        state = run.ctx.session(run.inputs.get("session"))
        step = self._compiled(run.node, run.config)
        result = await run.ctx.run_step(run.node.id, state, step, label=run.node.label or None)
        return NodeResult({"session": state.handle()}, f"{result.duration_ms} ms")


def _description(node: GraphNode, fallback: str) -> str:
    return (node.label or fallback)[:300]


class NavigateConfig(_Config):
    url: str = Field(
        default="/",
        min_length=1,
        max_length=2000,
        description="A path on the environment URL (/login) or a full URL on an allowed domain.",
    )
    timeout_ms: int | None = Field(default=None, ge=100, le=120_000)


class NavigateNode(_StepNode):
    type_id = "browser.navigate"
    label = "Navigate"
    description = "Opens a page."
    config_model = NavigateConfig

    def step(self, config: BaseModel, node: GraphNode) -> Step:
        assert isinstance(config, NavigateConfig)
        return Step(
            action="goto",
            description=_description(node, f"Open {config.url}"),
            value=config.url,
            timeout_ms=config.timeout_ms,
        )


def _default_locator() -> Locator:
    return Locator(strategy="role", role="button", value="Submit")


class ClickConfig(_Config):
    locator: Locator = Field(default_factory=_default_locator)
    timeout_ms: int | None = Field(default=None, ge=100, le=120_000)


class ClickNode(_StepNode):
    type_id = "browser.click"
    label = "Click"
    description = "Clicks an element."
    config_model = ClickConfig

    def step(self, config: BaseModel, node: GraphNode) -> Step:
        assert isinstance(config, ClickConfig)
        return Step(
            action="click",
            description=_description(node, "Click"),
            locator=config.locator,
            timeout_ms=config.timeout_ms,
        )


def _field_locator() -> Locator:
    return Locator(strategy="label", value="Email")


class FillConfig(_Config):
    locator: Locator = Field(default_factory=_field_locator)
    value: str = Field(
        default="",
        max_length=2000,
        description="Text to type. Use {{env.NAME}} or {{secret.NAME}} for test data.",
    )
    timeout_ms: int | None = Field(default=None, ge=100, le=120_000)


class FillNode(_StepNode):
    type_id = "browser.fill"
    label = "Fill Input"
    description = "Types into a field (secrets are masked in screenshots)."
    config_model = FillConfig

    def step(self, config: BaseModel, node: GraphNode) -> Step:
        assert isinstance(config, FillConfig)
        return Step(
            action="fill",
            description=_description(node, "Fill"),
            locator=config.locator,
            value=config.value,
            timeout_ms=config.timeout_ms,
        )


class SelectConfig(_Config):
    locator: Locator = Field(default_factory=lambda: Locator(strategy="label", value="Country"))
    value: str = Field(default="", max_length=2000, description="Option value or label.")
    timeout_ms: int | None = Field(default=None, ge=100, le=120_000)


class SelectOptionNode(_StepNode):
    type_id = "browser.select_option"
    label = "Select Option"
    description = "Chooses an option in a select box."
    config_model = SelectConfig

    def step(self, config: BaseModel, node: GraphNode) -> Step:
        assert isinstance(config, SelectConfig)
        return Step(
            action="select_option",
            description=_description(node, "Select"),
            locator=config.locator,
            value=config.value,
            timeout_ms=config.timeout_ms,
        )


class PressConfig(_Config):
    key: str = Field(default="Enter", min_length=1, max_length=40, description="e.g. Enter, Tab")
    locator: Locator | None = Field(default=None, description="Focus this element first.")


class PressNode(_StepNode):
    type_id = "browser.press"
    label = "Press Key"
    description = "Presses a key, optionally on an element."
    config_model = PressConfig

    def step(self, config: BaseModel, node: GraphNode) -> Step:
        assert isinstance(config, PressConfig)
        return Step(
            action="press",
            description=_description(node, f"Press {config.key}"),
            locator=config.locator,
            value=config.key,
        )


class WaitConfig(_Config):
    locator: Locator = Field(default_factory=lambda: Locator(strategy="text", value="Welcome"))
    state: Literal["visible", "hidden", "attached", "detached"] = "visible"
    timeout_ms: int | None = Field(default=None, ge=100, le=120_000)


class WaitNode(_StepNode):
    type_id = "browser.wait"
    label = "Wait"
    description = "Waits for an element to appear or disappear."
    config_model = WaitConfig

    def step(self, config: BaseModel, node: GraphNode) -> Step:
        assert isinstance(config, WaitConfig)
        return Step(
            action="wait_for",
            description=_description(node, "Wait"),
            locator=config.locator,
            state=config.state,
            timeout_ms=config.timeout_ms,
        )


class ScreenshotConfig(_Config):
    name: str = Field(default="checkpoint", pattern=r"^[a-z0-9][a-z0-9-]{0,59}$")


class ScreenshotNode(_StepNode):
    type_id = "browser.screenshot"
    label = "Screenshot"
    description = "Saves a full-page screenshot."
    config_model = ScreenshotConfig

    def step(self, config: BaseModel, node: GraphNode) -> Step:
        assert isinstance(config, ScreenshotConfig)
        return Step(
            action="screenshot", description=_description(node, "Screenshot"), value=config.name
        )


class AssertConfig(_Config):
    check: Literal["visible", "hidden", "text", "url", "title"] = "visible"
    locator: Locator | None = Field(
        default_factory=lambda: Locator(strategy="role", role="heading", value="Welcome"),
        description="Element to check (visible, hidden and text checks).",
    )
    expected: str = Field(default="", max_length=2000, description="Text, URL part or title.")
    match: Literal["contains", "exact"] = "contains"
    timeout_ms: int | None = Field(default=None, ge=100, le=120_000)


class AssertNode(_StepNode):
    type_id = "browser.assert"
    label = "Assert"
    description = "Checks that the page shows what it should."
    config_model = AssertConfig

    def step(self, config: BaseModel, node: GraphNode) -> Step:
        assert isinstance(config, AssertConfig)
        action = {
            "visible": "expect_visible",
            "hidden": "expect_hidden",
            "text": "expect_text",
            "url": "expect_url",
            "title": "expect_title",
        }[config.check]
        needs_locator = config.check in ("visible", "hidden", "text")
        needs_value = config.check in ("text", "url", "title")
        return Step(
            action=action,
            description=_description(node, f"Assert {config.check}"),
            locator=config.locator if needs_locator else None,
            value=config.expected if needs_value else None,
            match=config.match if needs_value else None,
            timeout_ms=config.timeout_ms,
        )


class InspectConsoleConfig(_Config):
    fail_on_errors: bool = Field(default=False, description="Fail when the page logged errors.")


class InspectConsoleNode(NodeType):
    type_id = "browser.inspect_console"
    category = "browser"
    label = "Inspect Console"
    description = "Reports console messages and page errors collected in the session so far."
    config_model = InspectConsoleConfig
    inputs = (SESSION_IN,)
    outputs = (SESSION_OUT, Port("report", "json", "Report"))

    async def execute(self, run: NodeRun) -> NodeResult:
        config = run.config
        assert isinstance(config, InspectConsoleConfig)
        state = run.ctx.session(run.inputs.get("session"))
        errors = [c for c in state.console if c.level in ("error", "pageerror")]
        report = {
            "messages": len(state.console),
            "errors": len(errors),
            "first_errors": [c.text for c in errors[:5]],
        }
        if config.fail_on_errors and errors:
            raise NodeError(
                "node.console_errors", f"The page logged {len(errors)} error(s): {errors[0].text}"
            )
        return NodeResult(
            {"session": state.handle(), "report": report},
            f"{report['messages']} messages, {report['errors']} errors",
        )


class InspectNetworkConfig(_Config):
    fail_on_status: int | None = Field(
        default=None, ge=400, le=599, description="Fail when a response has this status or higher."
    )


class InspectNetworkNode(NodeType):
    type_id = "browser.inspect_network"
    category = "browser"
    label = "Inspect Network"
    description = "Reports failed and blocked requests collected in the session so far."
    config_model = InspectNetworkConfig
    inputs = (SESSION_IN,)
    outputs = (SESSION_OUT, Port("report", "json", "Report"))

    async def execute(self, run: NodeRun) -> NodeResult:
        config = run.config
        assert isinstance(config, InspectNetworkConfig)
        state = run.ctx.session(run.inputs.get("session"))
        failures = state.network_failures
        report = {
            "failed": len(failures),
            "blocked": len(state.blocked),
            "requests": [
                {"method": f.method, "url": f.url, "status": f.status, "failure": f.failure}
                for f in failures[:10]
            ],
        }
        if config.fail_on_status is not None:
            bad = [
                f for f in failures if f.status is not None and f.status >= config.fail_on_status
            ]
            if bad:
                raise NodeError(
                    "node.network_errors", f"{bad[0].method} {bad[0].url} returned {bad[0].status}"
                )
        return NodeResult(
            {"session": state.handle(), "report": report},
            f"{report['failed']} failed, {report['blocked']} blocked",
        )


# ---------------------------------------------------------------------------- tests


async def _run_plan(run: NodeRun, plan: TestPlan, title: str) -> NodeResult:
    state = run.ctx.session(run.inputs.get("session"))
    passed = 0
    for index, step in enumerate(plan.steps):
        await run.ctx.emit(
            "browser.step.started",
            f"{title} — step {index + 1}: {step.description}",
            category="browser",
            node_id=run.node.id,
            data={"action": step.action, "test_step": index},
        )
        try:
            await run.ctx.run_step(run.node.id, state, step, label=f"{title} — step {index + 1}")
        except NodeError as exc:
            exc.message = f"Step {index + 1} ({step.description}) failed: {exc.message}"
            raise
        passed += 1
    result = {
        "status": "passed",
        "test": title,
        "steps_passed": passed,
        "steps_total": len(plan.steps),
    }
    return NodeResult({"session": state.handle(), "result": result}, f"{passed}/{passed} steps")


class RunVersionConfig(_Config):
    test_case_id: uuid.UUID | None = Field(
        default=None,
        description="The test to run (its current approved version).",
        json_schema_extra={"ui": "test_case"},
    )


class RunTestNode(NodeType):
    type_id = "test.run_version"
    category = "test"
    label = "Run Test"
    description = "Runs the current approved version of a test in the browser session."
    config_model = RunVersionConfig
    inputs = (SESSION_IN,)
    outputs = (SESSION_OUT, Port("result", "result", "Result"))

    def validate_static(
        self, node: GraphNode, config: BaseModel, ctx: ValidationContext
    ) -> Iterable[GraphIssue]:
        assert isinstance(config, RunVersionConfig)
        case = ctx.test_cases.get(str(config.test_case_id)) if config.test_case_id else None
        if case is None:
            yield GraphIssue(
                severity="error",
                code="node.test_missing",
                message="Choose a test of this project.",
                node_id=node.id,
            )
        elif case[1] is None:
            yield GraphIssue(
                severity="error",
                code="node.test_not_approved",
                message=f"'{case[0]}' has no approved version yet.",
                node_id=node.id,
            )

    async def execute(self, run: NodeRun) -> NodeResult:
        config = run.config
        assert isinstance(config, RunVersionConfig)
        async with run.ctx.session_factory() as db:
            row = (
                await db.execute(
                    select(TestCase, TestVersion)
                    .join(TestVersion, TestCase.current_version_id == TestVersion.id)
                    .where(TestCase.id == config.test_case_id)
                )
            ).one_or_none()
        if row is None:
            raise NodeError("node.test_not_approved", "The test has no approved version.")
        case, version = row
        plan = TestPlan.model_validate(version.plan)
        return await _run_plan(run, plan, f"{case.name} v{version.version}")


class RunPlanNode(NodeType):
    type_id = "test.run_plan"
    category = "test"
    label = "Run Plan"
    description = "Validates a generated test plan against the project and runs it."
    inputs = (SESSION_IN, Port("plan", "test_plan", "Test plan"))
    outputs = (SESSION_OUT, Port("result", "result", "Result"))

    async def execute(self, run: NodeRun) -> NodeResult:
        try:
            plan = TestPlan.model_validate(run.inputs.get("plan"))
        except ValidationError as exc:
            raise NodeError("node.invalid_plan", f"The plan is not valid: {exc}") from exc
        state = run.ctx.session(run.inputs.get("session"))
        env = state.environment
        issues = validate_plan(
            plan,
            allowed_domains=run.ctx.allowed_domains,
            variables={n: "secret" if v.is_secret else "env" for n, v in env.variables.items()},
            environment_name=env.name,
        )
        if has_errors(issues):
            first = next(i for i in issues if i.severity == "error")
            raise NodeError("node.plan_rejected", f"The plan was rejected: {first.message}")
        return await _run_plan(run, plan, plan.name)


# ---------------------------------------------------------------------------- AI


async def _ai_call(run: NodeRun, task: TaskCategory, **kwargs: Any) -> Any:
    async with run.ctx.session_factory() as db:
        try:
            result = await run.ctx.ai(db).run_structured(
                run.ctx.owner_id, task, origin="workflow", **kwargs
            )
        except AppError as exc:
            transient = exc.code in ("ai.rate_limited", "ai.provider_unavailable", "ai.timeout")
            raise NodeError(exc.code, exc.message, transient=transient) from exc
    record = result.record
    await run.ctx.emit(
        "ai.request.completed",
        f"{task.value.replace('_', ' ').capitalize()} answered by "
        f"{record.actual_provider_type}/{record.actual_model} in {record.latency_ms} ms",
        category="ai",
        node_id=run.node.id,
        data={
            "ai_request_id": str(record.id),
            "task": task.value,
            "requested_model": record.requested_model,
            "actual_provider": record.actual_provider_type,
            "actual_model": record.actual_model,
            "latency_ms": record.latency_ms,
            "total_tokens": record.total_tokens,
            "fallback_used": record.fallback_used,
            "external": True,
        },
    )
    return result.output


def _prompt_context(run: NodeRun) -> dict[str, Any]:
    env = run.ctx.environments.get("default") or next(iter(run.ctx.environments.values()))
    return {
        "base_url": env.base_url,
        "allowed_domains": run.ctx.allowed_domains,
        "variables": {n: "secret" if v.is_secret else "env" for n, v in env.variables.items()},
    }


class RequirementAnalyzerNode(NodeType):
    type_id = "ai.requirement_analyzer"
    category = "ai"
    label = "Requirement Analyzer"
    description = "Turns a plain-language scenario into requirements, test data and open questions."
    inputs = (Port("scenario", "text", "Scenario"),)
    outputs = (Port("analysis", "analysis", "Analysis"),)

    async def execute(self, run: NodeRun) -> NodeResult:
        scenario = str(run.inputs.get("scenario") or "").strip()
        if not scenario:
            raise NodeError("node.scenario_missing", "The scenario text is empty.")
        analysis = await _ai_call(
            run,
            TaskCategory.REQUIREMENT_ANALYSIS,
            system=prompts.ANALYSIS_SYSTEM,
            prompt=prompts.analysis_prompt(scenario, **_prompt_context(run)),
            output_model=RequirementAnalysis,
        )
        return NodeResult(
            {"analysis": analysis.model_dump(mode="json")},
            f"{len(analysis.requirements)} requirements",
        )


class TestPlannerNode(NodeType):
    __test__ = False
    type_id = "ai.test_planner"
    category = "ai"
    label = "Test Planner"
    description = "Writes a structured test plan (restricted action DSL) for the scenario."
    inputs = (
        Port("scenario", "text", "Scenario"),
        Port("analysis", "analysis", "Analysis", required=False),
    )
    outputs = (Port("plan", "test_plan", "Test plan"),)

    async def execute(self, run: NodeRun) -> NodeResult:
        scenario = str(run.inputs.get("scenario") or "").strip()
        if not scenario:
            raise NodeError("node.scenario_missing", "The scenario text is empty.")
        context = _prompt_context(run)
        raw = run.inputs.get("analysis")
        if raw is None:
            analysis = await _ai_call(
                run,
                TaskCategory.REQUIREMENT_ANALYSIS,
                system=prompts.ANALYSIS_SYSTEM,
                prompt=prompts.analysis_prompt(scenario, **context),
                output_model=RequirementAnalysis,
            )
        else:
            analysis = RequirementAnalysis.model_validate(raw)
        plan = await _ai_call(
            run,
            TaskCategory.TEST_PLANNING,
            system=prompts.PLANNING_SYSTEM,
            prompt=prompts.planning_prompt(scenario, analysis, **context),
            output_model=TestPlan,
            max_output_tokens=8192,
        )
        return NodeResult({"plan": plan.model_dump(mode="json")}, f"{len(plan.steps)} steps")


class FailureAnalyzerNode(NodeType):
    type_id = "ai.failure_analyzer"
    category = "ai"
    label = "Failure Analyzer"
    description = (
        "Explains why the connected node failed, from evidence the run collected: page, "
        "accessibility tree, console, network and (with a vision model) its last screenshot."
    )
    inputs = (Port("failure", "error", "Failure"),)
    outputs = (Port("analysis", "json", "Analysis"),)

    async def execute(self, run: NodeRun) -> NodeResult:
        from app.infrastructure.database.models import ExecutionEvent
        from app.services.ai.router import TaskRouter
        from app.services.quality.analysis import analyse, vision_supported
        from app.services.quality.evidence import node_evidence

        failure = run.inputs.get("failure")
        if not isinstance(failure, dict) or not failure.get("node_id"):
            raise NodeError("node.no_failure", "Connect the On error output of another node.")
        failed_id = str(failure["node_id"])
        state = run.ctx.node_sessions.get(failed_id)
        async with run.ctx.session_factory() as db:
            events = list(
                (
                    await db.execute(
                        select(ExecutionEvent)
                        .where(
                            ExecutionEvent.execution_id == run.ctx.execution.id,
                            ExecutionEvent.node_id == failed_id,
                        )
                        .order_by(ExecutionEvent.seq)
                        .limit(1000)
                    )
                ).scalars()
            )
        evidence = node_evidence(
            node_label=run.ctx.node_labels.get(failed_id, failed_id),
            error_code=str(failure.get("code", "unknown")),
            error_message=str(failure.get("message", "")),
            url=state.url if state else None,
            snapshot=state.last_snapshot if state else None,
            events=events,
            failed_node_id=failed_id,
        )
        async with run.ctx.session_factory() as db:
            image = None
            if await vision_supported(
                TaskRouter(db, run.ctx.providers), run.ctx.owner_id, TaskCategory.FAILURE_ANALYSIS
            ):
                image = run.ctx.frame_bytes(failed_id)
            try:
                output, request_id = await analyse(
                    run.ctx.ai(db), run.ctx.owner_id, evidence=evidence, scenario="", image=image
                )
            except AppError as exc:
                transient = exc.code in ("ai.rate_limited", "ai.provider_unavailable", "ai.timeout")
                raise NodeError(exc.code, exc.message, transient=transient) from exc
        await run.ctx.emit(
            "ai.request.completed",
            f"Failure analysis: {output.category}, recommended {output.recommended_action}",
            category="ai",
            node_id=run.node.id,
            data={
                "ai_request_id": request_id,
                "task": "failure_analysis",
                "used_screenshot": image is not None,
                "external": True,
            },
        )
        return NodeResult(
            {"analysis": {"evidence": evidence, **output.model_dump(mode="json")}},
            f"{output.category} → {output.recommended_action}",
        )


# ---------------------------------------------------------------------------- logic


class ConditionConfig(_Config):
    path: str = Field(
        default="status",
        max_length=200,
        pattern=r"^$|^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$",
        description="Dotted path into the input value, e.g. status or report.errors.",
    )
    operator: Literal[
        "equals", "not_equals", "contains", "greater_than", "less_than", "exists", "is_empty"
    ] = "equals"
    value: str = Field(default="passed", max_length=500, description="Compared as text or number.")


def lookup(value: Any, path: str) -> tuple[bool, Any]:
    current = value
    for part in [p for p in path.split(".") if p]:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False, None
    return True, current


def evaluate(config: ConditionConfig, value: Any) -> bool:
    """A closed set of comparisons over JSON data: no expressions are evaluated."""
    found, actual = lookup(value, config.path)
    if config.operator == "exists":
        return found and actual is not None
    if config.operator == "is_empty":
        return not found or actual in (None, "", [], {}, 0)
    if not found:
        return config.operator == "not_equals"
    if config.operator in ("greater_than", "less_than"):
        try:
            left, right = float(actual), float(config.value)
        except (TypeError, ValueError):
            return False
        return left > right if config.operator == "greater_than" else left < right
    text = str(actual).lower()
    expected = config.value.lower()
    if config.operator == "contains":
        if isinstance(actual, list):
            return any(str(item).lower() == expected for item in actual)
        return expected in text
    equal = text == expected
    return equal if config.operator == "equals" else not equal


class ConditionNode(NodeType):
    type_id = "logic.condition"
    category = "logic"
    label = "Condition"
    description = "Sends the input down the true or the false branch."
    config_model = ConditionConfig
    inputs = (Port("value", "any", "Value"),)
    outputs = (Port("true", "any", "True"), Port("false", "any", "False"))
    has_error_output = False

    async def execute(self, run: NodeRun) -> NodeResult:
        config = run.config
        assert isinstance(config, ConditionConfig)
        value = run.inputs.get("value")
        branch = "true" if evaluate(config, value) else "false"
        return NodeResult({branch: value}, f"{config.path} {config.operator} → {branch}")


class MergeNode(NodeType):
    type_id = "logic.merge"
    category = "logic"
    label = "Merge"
    description = "Waits for every incoming branch and continues with the values that arrived."
    inputs = (Port("inputs", "any", "Inputs", multi=True),)
    outputs = (Port("value", "any", "Values"),)
    has_error_output = False

    async def execute(self, run: NodeRun) -> NodeResult:
        values = run.inputs.get("inputs") or []
        return NodeResult({"value": values}, f"{len(values)} inputs")


class DelayConfig(_Config):
    seconds: float = Field(default=1.0, ge=0, le=300)


class DelayNode(NodeType):
    type_id = "logic.delay"
    category = "logic"
    label = "Delay"
    description = "Waits, then passes the input on unchanged."
    config_model = DelayConfig
    inputs = (Port("value", "any", "Value", required=False),)
    outputs = (Port("value", "any", "Value"),)
    entry = True
    has_error_output = False

    async def execute(self, run: NodeRun) -> NodeResult:
        config = run.config
        assert isinstance(config, DelayConfig)
        await asyncio.sleep(config.seconds)
        return NodeResult({"value": run.inputs.get("value")}, f"waited {config.seconds:g}s")


# ---------------------------------------------------------------------------- planned


def _planned(type_id: str, category: str, label: str, description: str, milestone: int) -> type:
    return type(
        f"Planned_{type_id.replace('.', '_')}",
        (PlannedNode,),
        {
            "type_id": type_id,
            "category": category,
            "label": label,
            "description": description,
            "milestone": milestone,
            "config_model": EmptyConfig,
        },
    )


PLANNED: list[type[NodeType]] = [
    _planned(
        "ai.code_generator",
        "ai",
        "Playwright Code Generator",
        "AI-written Playwright code for review.",
        8,
    ),
    _planned(
        "ai.visual_analyzer", "ai", "Visual Analyzer", "Checks screenshots with a vision model.", 8
    ),
    _planned(
        "ai.repair_proposal",
        "ai",
        "Test Repair Proposal",
        "Proposes a fix for human approval (available today from a failed test run).",
        8,
    ),
    _planned("ai.report_generator", "ai", "Report Generator", "Writes a run report.", 8),
    _planned("logic.switch", "logic", "Switch", "Routes to one of several cases.", 8),
    _planned("logic.approval_gate", "logic", "Approval Gate", "Pauses until a person approves.", 8),
    _planned("data.transform", "data", "Transform Data", "Reshapes JSON with a mapping.", 8),
    _planned("data.validate_schema", "data", "Validate Schema", "Checks JSON against a schema.", 8),
    _planned("data.store_artifact", "data", "Store Artifact", "Saves data as a run artifact.", 8),
]

AVAILABLE: list[type[NodeType]] = [
    InputNode,
    OutputNode,
    LaunchBrowserNode,
    NavigateNode,
    ClickNode,
    FillNode,
    SelectOptionNode,
    PressNode,
    WaitNode,
    ScreenshotNode,
    AssertNode,
    InspectConsoleNode,
    InspectNetworkNode,
    RunTestNode,
    RunPlanNode,
    RequirementAnalyzerNode,
    TestPlannerNode,
    FailureAnalyzerNode,
    ConditionNode,
    MergeNode,
    DelayNode,
]
