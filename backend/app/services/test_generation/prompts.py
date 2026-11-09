"""Prompts for the test-generation pipeline. Scenario text is always wrapped as untrusted data."""

from __future__ import annotations

import json

from app.schemas.testing import RequirementAnalysis


def _variables_block(variables: dict[str, str]) -> str:
    if not variables:
        return "No test data variables are defined yet."
    lines = [
        f"- {name} ({'secret' if kind == 'secret' else 'plain'})"
        for name, kind in sorted(variables.items())
    ]
    return (
        "Test data variables already defined (names only; values are never shown to you):\n"
        + "\n".join(lines)
    )


def _context(base_url: str, allowed_domains: list[str], variables: dict[str, str]) -> str:
    return (
        f"Application under test: {base_url}\n"
        f"Allowed domains: {', '.join(allowed_domains)}\n"
        f"{_variables_block(variables)}"
    )


ANALYSIS_SYSTEM = (
    "You are a senior QA analyst preparing an end-to-end browser test for TestPilot. "
    "Break the user's scenario into separate, observable, testable requirements. "
    "List as test data only values that must not be hard-coded: credentials, account "
    "identifiers, personal data and values that differ between environments. Name them in "
    "UPPER_SNAKE_CASE; mark passwords, tokens and other credentials as kind 'secret', everything "
    "else as 'env'. Concrete example values the scenario states (an item title, a search term, an "
    "expected message) are not test data: keep them literal. Reuse existing variable names when "
    "they fit. Never invent concrete credentials or personal data. "
    "Record genuine ambiguities instead of guessing."
)


def analysis_prompt(
    scenario: str, *, base_url: str, allowed_domains: list[str], variables: dict[str, str]
) -> str:
    return (
        f"{_context(base_url, allowed_domains, variables)}\n\n"
        f"Scenario:\n<untrusted>\n{scenario}\n</untrusted>"
    )


PLANNING_SYSTEM = """You write browser test plans for TestPilot in a restricted JSON format.

Each step has an "action" and only the fields that action uses:
- goto: value = path starting with "/" (relative to the application URL) or a full URL on an allowed domain
- click, check, uncheck: locator
- fill, select_option: locator + value
- press: value = key name such as Enter or Tab; optional locator
- wait_for: locator; optional state (visible, hidden, attached, detached)
- expect_visible, expect_hidden: locator
- expect_text: locator + value; optional match (contains or exact)
- expect_url: value = URL fragment; optional match
- expect_title: value = title text; optional match
- screenshot: value = short-name-with-dashes

Locators: {"strategy": "role", "role": "button", "value": "<accessible name>"} is preferred, then
"label", "text", "placeholder", "test_id". Use "css" only when nothing user-facing exists. For an
element repeated in a list, prefer a role or text locator with "nth" (0-based) over CSS, for
example {"strategy": "role", "role": "checkbox", "value": "<accessible name>", "nth": 0}.

Test data: never write literal credentials or personal data. Use {{env.NAME}} or {{secret.NAME}}
for those and declare every name in "test_data". Secrets may only appear in fill or select_option.
Concrete values the scenario states that are not credentials or personal data (an item title, a
search term, an expected message) are written literally, without variables. Placeholders never
appear in locators.

Rules: start with goto; keep each description short and human readable; verify outcomes with
expect_* steps (at least one); at most 30 steps; stay on the allowed domains; do not add steps the
scenario does not ask for.

Example step list:
[{"action": "goto", "description": "Open the login page", "value": "/login"},
 {"action": "fill", "description": "Enter the email", "locator": {"strategy": "label", "value": "Email"}, "value": "{{env.LOGIN_EMAIL}}"},
 {"action": "click", "description": "Sign in", "locator": {"strategy": "role", "role": "button", "value": "Sign in"}},
 {"action": "expect_url", "description": "Dashboard opens", "value": "/dashboard"}]"""


def planning_prompt(
    scenario: str,
    analysis: RequirementAnalysis,
    *,
    base_url: str,
    allowed_domains: list[str],
    variables: dict[str, str],
) -> str:
    return (
        f"{_context(base_url, allowed_domains, variables)}\n\n"
        "Requirement analysis (from the previous step):\n"
        f"{json.dumps(analysis.model_dump(mode='json'), indent=2)}\n\n"
        f"Scenario:\n<untrusted>\n{scenario}\n</untrusted>\n\n"
        "Write the complete test plan."
    )
