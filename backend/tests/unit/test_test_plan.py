"""Plan DSL rules, context validation and deterministic code rendering."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.domain.plan_validation import has_errors, host_allowed, validate_plan
from app.domain.test_plan import Step, TestPlan, placeholders
from app.services.test_generation.renderer import render

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"


def login_plan(**overrides: Any) -> TestPlan:
    data: dict[str, Any] = {
        "name": "Sign in and see the dashboard",
        "description": "A registered user signs in.",
        "preconditions": ["A test account exists"],
        "test_data": [
            {"name": "LOGIN_EMAIL", "kind": "env", "description": "Test account email"},
            {"name": "LOGIN_PASSWORD", "kind": "secret", "description": "Test account password"},
        ],
        "steps": [
            {"action": "goto", "description": "Open the login page", "value": "/login"},
            {
                "action": "fill",
                "description": "Enter the email",
                "locator": {"strategy": "label", "value": "Email"},
                "value": "{{env.LOGIN_EMAIL}}",
            },
            {
                "action": "fill",
                "description": "Enter the password",
                "locator": {"strategy": "label", "value": "Password"},
                "value": "{{secret.LOGIN_PASSWORD}}",
            },
            {
                "action": "click",
                "description": "Submit",
                "locator": {
                    "strategy": "role",
                    "role": "button",
                    "value": "Sign in",
                    "exact": True,
                },
            },
            {
                "action": "expect_url",
                "description": "Lands on the dashboard",
                "value": "/dashboard",
            },
            {
                "action": "expect_text",
                "description": "Greets the user",
                "locator": {"strategy": "role", "role": "heading", "value": "Dashboard"},
                "value": "Welcome, {{env.LOGIN_EMAIL}}",
                "match": "contains",
            },
            {"action": "screenshot", "description": "Capture the dashboard", "value": "dashboard"},
        ],
        "expected_results": ["The dashboard greets the user"],
    }
    data.update(overrides)
    return TestPlan.model_validate(data)


# ----------------------------------------------------------------------------- DSL


def test_valid_plan_and_placeholders() -> None:
    plan = login_plan()
    assert len(plan.steps) == 7
    assert placeholders("Hi {{env.A}} and {{ secret.B_2 }}") == [("env", "A"), ("secret", "B_2")]


@pytest.mark.parametrize(
    ("step", "message"),
    [
        ({"action": "click", "description": "x"}, "needs a locator"),
        ({"action": "goto", "description": "x"}, "needs a value"),
        (
            {
                "action": "goto",
                "description": "x",
                "value": "/a",
                "locator": {"strategy": "text", "value": "a"},
            },
            "does not take a locator",
        ),
        (
            {
                "action": "click",
                "description": "x",
                "locator": {"strategy": "text", "value": "a"},
                "value": "b",
            },
            "does not take a value",
        ),
        (
            {"action": "click", "description": "x", "locator": {"strategy": "role", "value": "Go"}},
            "needs 'role'",
        ),
        (
            {
                "action": "expect_text",
                "description": "x",
                "locator": {"strategy": "text", "value": "a"},
                "value": "{{secret.P}}",
            },
            "Secrets can only be used",
        ),
        (
            {
                "action": "fill",
                "description": "x",
                "locator": {"strategy": "label", "value": "a"},
                "value": "{{password}}",
            },
            "Invalid placeholder",
        ),
        ({"action": "press", "description": "x", "value": "rm -rf /"}, "press needs a key"),
        ({"action": "screenshot", "description": "x", "value": "../../etc"}, "Screenshot names"),
        (
            {"action": "goto", "description": "x", "value": "/a", "state": "visible"},
            "only used by wait_for",
        ),
        ({"action": "eval", "description": "x", "value": "alert(1)"}, "Input should be"),
    ],
)
def test_step_rules(step: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Step.model_validate(step)


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Step.model_validate({"action": "goto", "description": "x", "value": "/", "javascript": "x"})


def test_duplicate_test_data_names_are_rejected() -> None:
    with pytest.raises(ValidationError, match="declared once"):
        login_plan(test_data=[{"name": "A", "kind": "env"}, {"name": "A", "kind": "secret"}])


# ---------------------------------------------------------------------- validation


def test_wildcard_domains() -> None:
    assert host_allowed("shop.example.com", ["*.example.com"])
    assert not host_allowed("example.com", ["*.example.com"])
    assert host_allowed("EXAMPLE.com", ["example.com"])
    assert not host_allowed("evil-example.com", ["*.example.com", "example.com"])


def test_clean_plan_has_no_issues() -> None:
    issues = validate_plan(
        login_plan(),
        allowed_domains=["app.example.com"],
        variables={"LOGIN_EMAIL": "env", "LOGIN_PASSWORD": "secret"},
    )
    assert issues == []


def test_context_issues() -> None:
    plan = login_plan(
        test_data=[{"name": "LOGIN_EMAIL", "kind": "secret"}],
        steps=[
            {
                "action": "click",
                "description": "Click",
                "locator": {"strategy": "css", "value": "#go"},
            },
            {"action": "goto", "description": "Leave", "value": "https://evil.test/phish"},
            {"action": "goto", "description": "Bad", "value": "login"},
            {
                "action": "fill",
                "description": "Email",
                "locator": {"strategy": "label", "value": "Email"},
                "value": "{{env.LOGIN_EMAIL}}",
            },
            {
                "action": "fill",
                "description": "Token",
                "locator": {"strategy": "label", "value": "Token"},
                "value": "{{secret.API_TOKEN}}",
            },
        ],
    )
    issues = validate_plan(
        plan, allowed_domains=["app.example.com"], variables={"API_TOKEN": "env"}
    )
    codes = {(i.code, i.step) for i in issues}
    assert ("plan.no_initial_navigation", 0) in codes
    assert ("plan.no_assertions", None) in codes
    assert ("plan.brittle_locator", 0) in codes
    assert ("plan.domain_not_allowed", 1) in codes
    assert ("plan.invalid_url", 2) in codes
    assert ("plan.test_data_kind_mismatch", 3) in codes
    assert ("plan.variable_missing", 3) in codes
    assert ("plan.undeclared_test_data", 4) in codes
    assert ("plan.secret_stored_plain", 4) in codes
    assert has_errors(issues)


# ------------------------------------------------------------------------ renderer


def test_rendering_is_deterministic_and_keeps_secrets_out() -> None:
    plan = login_plan()
    first = render(plan, base_url="https://app.example.com/", version=3)
    second = render(login_plan(), base_url="https://app.example.com/", version=3)
    assert first == second
    for code in (first.python, first.typescript):
        assert "approved test version 3" in code
        assert 'env("LOGIN_PASSWORD")' in code
        assert "{{" not in code


def test_python_output_is_valid_and_idiomatic() -> None:
    code = render(login_plan(), base_url="https://app.example.com").python
    compile(code, "test_generated.py", "exec")  # syntax check
    assert 'BASE_URL = os.environ.get("TESTPILOT_BASE_URL", "https://app.example.com")' in code
    assert 'page.goto(BASE_URL + "/login")' in code
    assert 'page.get_by_label("Email").fill(env("LOGIN_EMAIL"))' in code
    assert 'page.get_by_role("button", name="Sign in", exact=True).click()' in code
    assert 'expect(page).to_have_url(re.compile(re.escape("/dashboard")))' in code
    assert 'to_contain_text("Welcome, " + env("LOGIN_EMAIL"))' in code
    assert 'page.screenshot(path="screenshots/dashboard.png", full_page=True)' in code
    assert "def test_sign_in_and_see_the_dashboard(page: Page) -> None:" in code
    assert "    # 4. Submit" in code


def test_typescript_output_shape() -> None:
    code = render(login_plan(), base_url="https://app.example.com").typescript
    assert 'import { test, expect } from "@playwright/test";' in code
    assert 'await page.getByLabel("Email").fill(env("LOGIN_EMAIL"));' in code
    assert 'await page.getByRole("button", { name: "Sign in", exact: true }).click();' in code
    assert 'await expect(page).toHaveURL(new RegExp(escapeRegExp("/dashboard")));' in code
    assert 'test("Sign in and see the dashboard", async ({ page }) => {' in code


def test_rendered_strings_are_escaped() -> None:
    plan = login_plan(
        name='Quote " and back\\slash',
        steps=[
            {"action": "goto", "description": "Open", "value": "/"},
            {
                "action": "expect_text",
                "description": "Odd text",
                "locator": {"strategy": "text", "value": 'He said "hi"\\n'},
                "value": "Line\nbreak",
                "match": "exact",
            },
        ],
        test_data=[],
    )
    code = render(plan, base_url="https://a.example").python
    compile(code, "test_generated.py", "exec")
    assert '"He said \\"hi\\"\\\\n"' in code


@pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules" / "typescript").exists(),
    reason="Node.js and frontend/node_modules/typescript are needed for the TypeScript syntax check",
)
def test_typescript_output_has_no_syntax_errors(tmp_path: Path) -> None:
    code = render(login_plan(), base_url="https://app.example.com").typescript
    script = tmp_path / "check.cjs"
    script.write_text(
        "const ts = require(process.argv[2]);\n"
        "const src = require('fs').readFileSync(0, 'utf8');\n"
        "const out = ts.transpileModule(src, { reportDiagnostics: true, compilerOptions: { target: 99 } });\n"
        "process.stdout.write(JSON.stringify((out.diagnostics || []).map(d => "
        "ts.flattenDiagnosticMessageText(d.messageText, ' '))));\n",
        encoding="utf-8",
    )
    result = subprocess.run(  # noqa: S603 - fixed local tool
        ["node", str(script), str(FRONTEND / "node_modules" / "typescript")],  # noqa: S607
        input=code,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert json.loads(result.stdout) == []
