"""The restricted test-plan DSL (ADR-004).

A plan is data, not code: a closed set of browser actions with structured locators. It is what the
AI produces, what users edit and approve, what the browser worker will execute (milestone 4), and
the single source from which Playwright code is rendered.

The step model is deliberately flat (one object type, nullable fields, an ``action`` enum) so its
JSON Schema works with every provider's structured-output subset; per-action rules are enforced
by a validator instead of a discriminated union.

Test data never appears literally: values reference ``{{env.NAME}}`` or ``{{secret.NAME}}``.
"""

from __future__ import annotations

import re
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VARIABLE_NAME = r"[A-Z][A-Z0-9_]{0,63}"
PLACEHOLDER = re.compile(r"\{\{\s*(env|secret)\.(" + VARIABLE_NAME + r")\s*\}\}")
ANY_TEMPLATE = re.compile(r"\{\{.*?\}\}")
KEY_NAME = re.compile(r"^[A-Za-z0-9]+(\+[A-Za-z0-9]+)*$")
SCREENSHOT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")

Action = Literal[
    "goto",
    "click",
    "fill",
    "select_option",
    "check",
    "uncheck",
    "press",
    "wait_for",
    "expect_visible",
    "expect_hidden",
    "expect_text",
    "expect_url",
    "expect_title",
    "screenshot",
]

AriaRole = Literal[
    "alert",
    "article",
    "banner",
    "button",
    "cell",
    "checkbox",
    "combobox",
    "dialog",
    "form",
    "heading",
    "img",
    "link",
    "list",
    "listbox",
    "listitem",
    "main",
    "menu",
    "menuitem",
    "navigation",
    "option",
    "paragraph",
    "progressbar",
    "radio",
    "region",
    "row",
    "searchbox",
    "slider",
    "spinbutton",
    "status",
    "switch",
    "tab",
    "table",
    "tabpanel",
    "textbox",
]

LOCATOR_REQUIRED: frozenset[str] = frozenset(
    {
        "click",
        "fill",
        "select_option",
        "check",
        "uncheck",
        "wait_for",
        "expect_visible",
        "expect_hidden",
        "expect_text",
    }
)
LOCATOR_FORBIDDEN: frozenset[str] = frozenset({"goto", "expect_url", "expect_title", "screenshot"})
VALUE_REQUIRED: frozenset[str] = frozenset(
    {
        "goto",
        "fill",
        "select_option",
        "press",
        "expect_text",
        "expect_url",
        "expect_title",
        "screenshot",
    }
)
ASSERTIONS: frozenset[str] = frozenset(
    {"expect_visible", "expect_hidden", "expect_text", "expect_url", "expect_title"}
)
# Secrets may only be typed into the page, never asserted on or put in URLs/screenshots names.
SECRET_ALLOWED: frozenset[str] = frozenset({"fill", "select_option"})


def placeholders(text: str | None) -> list[tuple[str, str]]:
    """``[(kind, NAME), ...]`` for every ``{{env.NAME}}`` / ``{{secret.NAME}}`` in ``text``."""
    return [(m.group(1), m.group(2)) for m in PLACEHOLDER.finditer(text or "")]


class Locator(BaseModel):
    """How to find an element. Prefer user-facing strategies (role, label, text) over CSS."""

    model_config = ConfigDict(extra="forbid")

    strategy: Literal["role", "label", "text", "placeholder", "test_id", "css"]
    value: str = Field(
        min_length=1,
        max_length=300,
        description=(
            "Accessible name for role; label/text/placeholder/test id/CSS selector otherwise."
        ),
    )
    role: AriaRole | None = Field(
        default=None, description="ARIA role; required for strategy 'role'."
    )
    exact: bool = False
    nth: int | None = Field(default=None, ge=0, le=50, description="0-based index among matches.")

    @model_validator(mode="after")
    def _role(self) -> Locator:
        if self.strategy == "role" and self.role is None:
            raise ValueError("A role locator needs 'role' (e.g. button, link, textbox).")
        if self.strategy != "role" and self.role is not None:
            raise ValueError("'role' is only used with the 'role' strategy.")
        if ANY_TEMPLATE.search(self.value):
            raise ValueError("Locators must not contain {{...}} placeholders.")
        return self


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Action
    description: str = Field(
        min_length=1, max_length=300, description="What this step does, for humans."
    )
    locator: Locator | None = None
    value: str | None = Field(
        default=None,
        max_length=2000,
        description=(
            "goto: path or URL; fill/select_option: text; press: key such as Enter; expect_text: "
            "expected text; expect_url: URL fragment; expect_title: title; screenshot: file name."
        ),
    )
    match: Literal["contains", "exact"] | None = Field(
        default=None, description="For expect_text, expect_url and expect_title. Default contains."
    )
    state: Literal["visible", "hidden", "attached", "detached"] | None = Field(
        default=None, description="For wait_for. Default visible."
    )
    timeout_ms: int | None = Field(default=None, ge=100, le=120_000)

    @field_validator("description")
    @classmethod
    def _description(cls, value: str) -> str:
        return " ".join(value.split())

    @model_validator(mode="after")
    def _per_action(self) -> Step:
        action = self.action
        if action in LOCATOR_REQUIRED and self.locator is None:
            raise ValueError(f"'{action}' needs a locator.")
        if action in LOCATOR_FORBIDDEN and self.locator is not None:
            raise ValueError(f"'{action}' does not take a locator.")
        if action in VALUE_REQUIRED and not (self.value or "").strip():
            raise ValueError(f"'{action}' needs a value.")
        if action not in VALUE_REQUIRED and self.value not in (None, ""):
            raise ValueError(f"'{action}' does not take a value.")
        if self.value == "":
            self.value = None
        if self.match is not None and action not in {"expect_text", "expect_url", "expect_title"}:
            raise ValueError("'match' is only used by expect_text, expect_url and expect_title.")
        if self.state is not None and action != "wait_for":
            raise ValueError("'state' is only used by wait_for.")
        if action == "press" and self.value and not KEY_NAME.match(self.value):
            raise ValueError("press needs a key such as Enter, Tab or Control+A.")
        if action == "screenshot" and self.value and not SCREENSHOT_NAME.match(self.value):
            raise ValueError("Screenshot names use lowercase letters, digits and dashes.")
        if self.value:
            for template in ANY_TEMPLATE.findall(self.value):
                if not PLACEHOLDER.fullmatch(template):
                    raise ValueError(
                        f"Invalid placeholder {template}: "
                        "use {{env.NAME}} or {{secret.NAME}}."
                    )
            if action not in SECRET_ALLOWED and any(
                k == "secret" for k, _ in placeholders(self.value)
            ):
                raise ValueError("Secrets can only be used in fill or select_option steps.")
        return self


class TestDataRef(BaseModel):
    __test__: ClassVar[bool] = False  # not a pytest test class
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        pattern=f"^{VARIABLE_NAME}$", description="Environment variable name, UPPER_SNAKE_CASE."
    )
    kind: Literal["env", "secret"]
    description: str = Field(default="", max_length=300)


class TestPlan(BaseModel):
    __test__: ClassVar[bool] = False  # not a pytest test class
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    preconditions: list[str] = Field(default_factory=list, max_length=20)
    test_data: list[TestDataRef] = Field(default_factory=list, max_length=30)
    steps: list[Step] = Field(min_length=1, max_length=100)
    expected_results: list[str] = Field(default_factory=list, max_length=30)
    cleanup: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("preconditions", "expected_results", "cleanup")
    @classmethod
    def _lines(cls, values: list[str]) -> list[str]:
        cleaned = [" ".join(v.split())[:300] for v in values]
        return [v for v in cleaned if v]

    @model_validator(mode="after")
    def _unique_data(self) -> TestPlan:
        names = [ref.name for ref in self.test_data]
        if len(names) != len(set(names)):
            raise ValueError("Each test data name must be declared once.")
        return self
