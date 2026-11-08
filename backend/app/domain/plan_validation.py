"""Context-aware checks on a TestPlan (beyond its schema): domains, test data, robustness.

Errors block approval. Warnings are shown to the reviewer but do not block.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal
from urllib.parse import urlsplit

from app.domain.test_plan import ASSERTIONS, TestPlan, placeholders

Severity = Literal["error", "warning"]


@dataclass(frozen=True, slots=True)
class PlanIssue:
    severity: Severity
    code: str
    message: str
    step: int | None = None  # 0-based step index

    def to_json(self) -> dict[str, object]:
        return asdict(self)


def normalize_domain(value: str) -> str:
    return value.strip().lower().rstrip(".")


def host_allowed(host: str, allowed_domains: list[str]) -> bool:
    host = normalize_domain(host)
    for pattern in (normalize_domain(d) for d in allowed_domains):
        if pattern.startswith("*."):
            suffix = pattern[1:]  # ".example.com"
            if host.endswith(suffix) and host != suffix.lstrip("."):
                return True
        elif host == pattern:
            return True
    return False


def validate_plan(
    plan: TestPlan,
    *,
    allowed_domains: list[str],
    variables: dict[str, str] | None = None,
    environment_name: str | None = None,
) -> list[PlanIssue]:
    """``variables`` maps variable name -> "env" | "secret" for the selected environment."""
    issues: list[PlanIssue] = []
    declared = {ref.name: ref.kind for ref in plan.test_data}
    reported_undeclared: set[str] = set()
    reported_missing: set[str] = set()

    if plan.steps[0].action != "goto":
        issues.append(
            PlanIssue(
                "warning",
                "plan.no_initial_navigation",
                "The plan does not start by opening a page.",
                0,
            )
        )
    if not any(step.action in ASSERTIONS for step in plan.steps):
        issues.append(
            PlanIssue(
                "warning",
                "plan.no_assertions",
                "The plan has no expect_* step, so it cannot fail on wrong behaviour.",
            )
        )

    for index, step in enumerate(plan.steps):
        if step.action == "goto" and step.value:
            target = step.value.strip()
            if target.startswith(("http://", "https://")):
                host = urlsplit(target).hostname or ""
                if not host or not host_allowed(host, allowed_domains):
                    issues.append(
                        PlanIssue(
                            "error",
                            "plan.domain_not_allowed",
                            f"{host or target} is not in this project's allowed domains.",
                            index,
                        )
                    )
            elif not target.startswith("/") and not target.startswith("{{"):
                issues.append(
                    PlanIssue(
                        "error",
                        "plan.invalid_url",
                        "Use a path starting with / (relative to the environment URL) "
                        "or a full https:// URL.",
                        index,
                    )
                )

        if step.locator and step.locator.strategy == "css":
            issues.append(
                PlanIssue(
                    "warning",
                    "plan.brittle_locator",
                    "CSS selectors break easily; prefer role, label, text or test id.",
                    index,
                )
            )

        for kind, name in placeholders(step.value):
            if name not in declared:
                if name not in reported_undeclared:
                    issues.append(
                        PlanIssue(
                            "warning",
                            "plan.undeclared_test_data",
                            f"{name} is used but not listed in the plan's test data.",
                            index,
                        )
                    )
                    reported_undeclared.add(name)
            elif declared[name] != kind:
                issues.append(
                    PlanIssue(
                        "error",
                        "plan.test_data_kind_mismatch",
                        f"{name} is declared as {declared[name]} but used as {kind}.",
                        index,
                    )
                )
            if variables is not None and name not in variables and name not in reported_missing:
                where = f" in environment '{environment_name}'" if environment_name else ""
                issues.append(
                    PlanIssue(
                        "warning",
                        "plan.variable_missing",
                        f"{name} has no value{where} yet. Add it before running the test.",
                        index,
                    )
                )
                reported_missing.add(name)
            elif variables is not None and kind == "secret" and variables.get(name) == "env":
                issues.append(
                    PlanIssue(
                        "warning",
                        "plan.secret_stored_plain",
                        f"{name} is used as a secret but stored as a plain variable.",
                        index,
                    )
                )
    return issues


def has_errors(issues: list[PlanIssue]) -> bool:
    return any(issue.severity == "error" for issue in issues)
