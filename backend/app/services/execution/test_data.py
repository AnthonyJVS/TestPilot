"""Turning an approved plan into browser commands: test data substitution and secret scrubbing.

Placeholders are resolved only here, inside the orchestrator, right before commands go to the
browser worker. Secret values never reach events, logs, AI prompts or the database; anything the
worker sends back is scrubbed of them before it is persisted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.test_plan import PLACEHOLDER, Step, TestPlan, placeholders
from browser_worker.protocol import BrowserLocator, BrowserStep

MIN_SCRUB_LENGTH = 3


@dataclass(frozen=True, slots=True)
class Variable:
    name: str
    value: str
    is_secret: bool


@dataclass(frozen=True, slots=True)
class BrowserCommand:
    step: BrowserStep
    sensitive: bool  # the value was typed from a secret
    screenshot_name: str | None


class MissingVariablesError(Exception):
    def __init__(self, names: list[str]) -> None:
        super().__init__(", ".join(names))
        self.names = names


def required_variables(plan: TestPlan) -> list[tuple[str, str]]:
    """Every ``(kind, NAME)`` referenced by the plan's steps, in first-use order."""
    seen: list[tuple[str, str]] = []
    for step in plan.steps:
        for ref in placeholders(step.value):
            if ref not in seen:
                seen.append(ref)
    return seen


def missing_variables(plan: TestPlan, variables: dict[str, Variable]) -> list[str]:
    missing: list[str] = []
    for kind, name in required_variables(plan):
        variable = variables.get(name)
        if variable is None or variable.is_secret != (kind == "secret"):
            missing.append(f"{{{{{kind}.{name}}}}}")
    return missing


def _resolve(text: str, variables: dict[str, Variable]) -> str:
    return PLACEHOLDER.sub(lambda m: variables[m.group(2)].value, text)


def build_commands(plan: TestPlan, variables: dict[str, Variable]) -> list[BrowserCommand]:
    missing = missing_variables(plan, variables)
    if missing:
        raise MissingVariablesError(missing)
    return [_command(step, variables) for step in plan.steps]


def _command(step: Step, variables: dict[str, Variable]) -> BrowserCommand:
    locator = (
        BrowserLocator(
            strategy=step.locator.strategy,
            value=step.locator.value,
            role=step.locator.role,
            exact=step.locator.exact,
            nth=step.locator.nth,
        )
        if step.locator
        else None
    )
    sensitive = any(kind == "secret" for kind, _ in placeholders(step.value))
    value = _resolve(step.value, variables) if step.value is not None else None
    return BrowserCommand(
        step=BrowserStep(
            action=step.action,
            locator=locator,
            value=value,
            match=step.match,
            state=step.state,
            timeout_ms=step.timeout_ms,
        ),
        sensitive=sensitive,
        screenshot_name=step.value if step.action == "screenshot" else None,
    )


class SecretScrubber:
    """Replaces secret values with ``[secret:NAME]`` in anything coming back from the browser."""

    def __init__(self, variables: dict[str, Variable]) -> None:
        pairs = [(v.value, v.name) for v in variables.values() if v.is_secret and v.value]
        # Longest first so a secret containing another is replaced whole.
        self._pairs = sorted(
            ((value, name) for value, name in pairs if len(value) >= MIN_SCRUB_LENGTH),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )

    def text(self, value: str) -> str:
        for secret, name in self._pairs:
            if secret in value:
                value = value.replace(secret, f"[secret:{name}]")
        return value

    def data(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {key: self.data(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.data(item) for item in value]
        return value
