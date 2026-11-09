"""Deterministic Playwright code from a TestPlan (ADR-004).

The same plan always renders the same code, so the code a reviewer reads is exactly the behaviour
that was approved. Test data placeholders become environment-variable lookups; secret values are
never written into code. No AI is involved here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.domain.test_plan import PLACEHOLDER, Locator, Step, TestPlan
from browser_worker.urls import path_after_base

RENDERER_VERSION = "1"


@dataclass(frozen=True, slots=True)
class RenderedCode:
    python: str
    typescript: str
    renderer_version: str = RENDERER_VERSION


def _literal(text: str) -> str:
    """A double-quoted string literal valid in both Python and TypeScript."""
    return json.dumps(text, ensure_ascii=False)


def _parts(text: str) -> list[tuple[str, str]]:
    """Split into ("literal", text) and ("var", NAME) parts."""
    parts: list[tuple[str, str]] = []
    position = 0
    for match in PLACEHOLDER.finditer(text):
        if match.start() > position:
            parts.append(("literal", text[position : match.start()]))
        parts.append(("var", match.group(2)))
        position = match.end()
    if position < len(text):
        parts.append(("literal", text[position:]))
    return parts or [("literal", "")]


class _Usage:
    def __init__(self) -> None:
        self.env = False
        self.regex = False


def _expr(text: str, usage: _Usage) -> str:
    pieces = []
    for kind, value in _parts(text):
        if kind == "var":
            usage.env = True
            pieces.append(f"env({_literal(value)})")
        else:
            pieces.append(_literal(value))
    return " + ".join(pieces)


def _url_expr(value: str, usage: _Usage, base: str, base_url: str) -> str:
    # Same joining as the browser worker: a path that repeats the base URL's path is not doubled.
    if not value.startswith("/"):
        return _expr(value, usage)
    rest = path_after_base(base_url, value)
    return f"{base} + {_expr(rest, usage)}" if rest else base


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:60]
    return slug or "scenario"


def _comment(index: int, step: Step) -> str:
    return f"{index}. {' '.join(step.description.split())}"


# ---------------------------------------------------------------------- Python


def _py_locator(locator: Locator) -> str:
    exact = ", exact=True" if locator.exact else ""
    value = _literal(locator.value)
    match locator.strategy:
        case "role":
            code = f"page.get_by_role({_literal(locator.role or '')}, name={value}{exact})"
        case "label":
            code = f"page.get_by_label({value}{exact})"
        case "text":
            code = f"page.get_by_text({value}{exact})"
        case "placeholder":
            code = f"page.get_by_placeholder({value}{exact})"
        case "test_id":
            code = f"page.get_by_test_id({value})"
        case _:
            code = f"page.locator({value})"
    return f"{code}.nth({locator.nth})" if locator.nth is not None else code


def _py_step(step: Step, usage: _Usage, base_url: str) -> str:
    loc = _py_locator(step.locator) if step.locator else ""
    timeout = f"timeout={step.timeout_ms}" if step.timeout_ms else ""
    t_only = f"({timeout})"
    t_extra = f", {timeout}" if timeout else ""
    value = step.value or ""
    match step.action:
        case "goto":
            return f"page.goto({_url_expr(value, usage, 'BASE_URL', base_url)}{t_extra})"
        case "click":
            return f"{loc}.click{t_only}"
        case "fill":
            return f"{loc}.fill({_expr(value, usage)}{t_extra})"
        case "select_option":
            return f"{loc}.select_option({_expr(value, usage)}{t_extra})"
        case "check":
            return f"{loc}.check{t_only}"
        case "uncheck":
            return f"{loc}.uncheck{t_only}"
        case "press":
            target = loc or "page.keyboard"
            return f"{target}.press({_literal(value)})"
        case "wait_for":
            return f'{loc}.wait_for(state="{step.state or "visible"}"{t_extra})'
        case "expect_visible":
            return f"expect({loc}).to_be_visible{t_only}"
        case "expect_hidden":
            return f"expect({loc}).to_be_hidden{t_only}"
        case "expect_text":
            method = "to_have_text" if step.match == "exact" else "to_contain_text"
            return f"expect({loc}).{method}({_expr(value, usage)}{t_extra})"
        case "expect_url" | "expect_title":
            method = "to_have_url" if step.action == "expect_url" else "to_have_title"
            expected = _expr(value, usage)
            if step.match != "exact":
                usage.regex = True
                expected = f"re.compile(re.escape({expected}))"
            return f"expect(page).{method}({expected}{t_extra})"
        case "screenshot":
            return f'page.screenshot(path="screenshots/{value}.png", full_page=True)'
    raise ValueError(f"Unsupported action {step.action}")  # pragma: no cover


def render_python(plan: TestPlan, *, base_url: str, version: int | None = None) -> str:
    usage = _Usage()
    body: list[str] = []
    for index, step in enumerate(plan.steps, start=1):
        body.append(f"    # {_comment(index, step)}")
        body.append(f"    {_py_step(step, usage, base_url)}")
    origin = f"approved test version {version}" if version else "a test plan"
    lines = [
        f"# {plan.name}",
        f"# Generated by TestPilot from {origin} (renderer v{RENDERER_VERSION}).",
        "# Do not edit by hand: change the plan in TestPilot and approve a new version.",
        "# Run with: pytest --browser chromium  (requires pytest-playwright)",
        "",
        "import os",
    ]
    if usage.regex:
        lines.append("import re")
    lines += [
        "",
        "from playwright.sync_api import Page, expect",
        "",
        f'BASE_URL = os.environ.get("TESTPILOT_BASE_URL", {_literal(base_url.rstrip("/"))})',
    ]
    if usage.env:
        lines += [
            "",
            "",
            "def env(name: str) -> str:",
            '    """Test data comes from environment variables; secrets are never stored in code."""',
            "    value = os.environ.get(name)",
            "    if value is None:",
            '        raise RuntimeError(f"Set the {name} environment variable before running this test.")',
            "    return value",
        ]
    lines += ["", "", f"def test_{_slug(plan.name)}(page: Page) -> None:", *body, ""]
    return "\n".join(lines)


# ------------------------------------------------------------------ TypeScript


def _ts_locator(locator: Locator) -> str:
    value = _literal(locator.value)
    match locator.strategy:
        case "role":
            options = f"{{ name: {value}{', exact: true' if locator.exact else ''} }}"
            code = f"page.getByRole({_literal(locator.role or '')}, {options})"
        case "label" | "text" | "placeholder":
            method = {
                "label": "getByLabel",
                "text": "getByText",
                "placeholder": "getByPlaceholder",
            }[locator.strategy]
            options = ", { exact: true }" if locator.exact else ""
            code = f"page.{method}({value}{options})"
        case "test_id":
            code = f"page.getByTestId({value})"
        case _:
            code = f"page.locator({value})"
    return f"{code}.nth({locator.nth})" if locator.nth is not None else code


def _ts_step(step: Step, usage: _Usage, base_url: str) -> str:
    loc = _ts_locator(step.locator) if step.locator else ""
    options = f"{{ timeout: {step.timeout_ms} }}" if step.timeout_ms else ""
    o_only = f"({options})"
    o_extra = f", {options}" if options else ""
    value = step.value or ""
    match step.action:
        case "goto":
            return f"await page.goto({_url_expr(value, usage, 'BASE_URL', base_url)}{o_extra});"
        case "click" | "check" | "uncheck":
            return f"await {loc}.{step.action}{o_only};"
        case "fill":
            return f"await {loc}.fill({_expr(value, usage)}{o_extra});"
        case "select_option":
            return f"await {loc}.selectOption({_expr(value, usage)}{o_extra});"
        case "press":
            return f"await {loc or 'page.keyboard'}.press({_literal(value)});"
        case "wait_for":
            timeout = f", timeout: {step.timeout_ms}" if step.timeout_ms else ""
            return f'await {loc}.waitFor({{ state: "{step.state or "visible"}"{timeout} }});'
        case "expect_visible":
            return f"await expect({loc}).toBeVisible{o_only};"
        case "expect_hidden":
            return f"await expect({loc}).toBeHidden{o_only};"
        case "expect_text":
            method = "toHaveText" if step.match == "exact" else "toContainText"
            return f"await expect({loc}).{method}({_expr(value, usage)}{o_extra});"
        case "expect_url" | "expect_title":
            method = "toHaveURL" if step.action == "expect_url" else "toHaveTitle"
            expected = _expr(value, usage)
            if step.match != "exact":
                usage.regex = True
                expected = f"new RegExp(escapeRegExp({expected}))"
            return f"await expect(page).{method}({expected}{o_extra});"
        case "screenshot":
            return f'await page.screenshot({{ path: "screenshots/{value}.png", fullPage: true }});'
    raise ValueError(f"Unsupported action {step.action}")  # pragma: no cover


def render_typescript(plan: TestPlan, *, base_url: str, version: int | None = None) -> str:
    usage = _Usage()
    body: list[str] = []
    for index, step in enumerate(plan.steps, start=1):
        body.append(f"  // {_comment(index, step)}")
        body.append(f"  {_ts_step(step, usage, base_url)}")
    origin = f"approved test version {version}" if version else "a test plan"
    lines = [
        f"// {plan.name}",
        f"// Generated by TestPilot from {origin} (renderer v{RENDERER_VERSION}).",
        "// Do not edit by hand: change the plan in TestPilot and approve a new version.",
        "// Run with: npx playwright test",
        'import { test, expect } from "@playwright/test";',
        "",
        f"const BASE_URL = process.env.TESTPILOT_BASE_URL ?? {_literal(base_url.rstrip('/'))};",
    ]
    if usage.env:
        lines += [
            "",
            "// Test data comes from environment variables; secrets are never stored in code.",
            "function env(name: string): string {",
            "  const value = process.env[name];",
            "  if (value === undefined) {",
            "    throw new Error(`Set the ${name} environment variable before running this test.`);",
            "  }",
            "  return value;",
            "}",
        ]
    if usage.regex:
        lines += [
            "",
            "function escapeRegExp(text: string): string {",
            '  return text.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&");',
            "}",
        ]
    lines += ["", f"test({_literal(plan.name)}, async ({{ page }}) => {{", *body, "});", ""]
    return "\n".join(lines)


def render(plan: TestPlan, *, base_url: str, version: int | None = None) -> RenderedCode:
    return RenderedCode(
        python=render_python(plan, base_url=base_url, version=version),
        typescript=render_typescript(plan, base_url=base_url, version=version),
    )
