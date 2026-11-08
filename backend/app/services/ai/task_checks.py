"""Routing check: one tiny, real structured call per task category.

Proves that the routed provider/model can perform the task end to end (credentials, model ID,
structured output, and vision for visual analysis) — and records capability evidence. Schemas are
deliberately simple (no length/enum constraints) so they work with every provider's JSON-schema
subset; answers are verified in Python instead.
"""

from __future__ import annotations

import struct
import uuid
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.services.ai import capabilities as caps
from app.services.ai.exceptions import AITaskFailedError
from app.services.ai.orchestrator import AIOrchestrator
from app.services.ai.types import (
    TASK_LABELS,
    Capability,
    CapabilityStatus,
    ImageInput,
    TaskCategory,
)

CheckStatus = Literal["passed", "failed", "error"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RequirementList(_Strict):
    requirements: list[str]


class PlanStep(_Strict):
    action: str
    target: str


class StepList(_Strict):
    steps: list[PlanStep]


class CodeSnippet(_Strict):
    code: str


class FailureClassification(_Strict):
    category: str
    summary: str


class ColourAnswer(_Strict):
    colour: str


class LocatorProposal(_Strict):
    locator: str


class OneLineSummary(_Strict):
    summary: str


def solid_png(rgb: tuple[int, int, int], size: int = 32) -> bytes:
    """A minimal valid PNG of one colour (no imaging library needed)."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    row = b"\x00" + bytes(rgb) * size
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * size))
        + chunk(b"IEND", b"")
    )


FAILURE_CATEGORIES = {
    "locator",
    "timeout",
    "assertion",
    "network",
    "environment",
    "test_data",
    "unknown",
}


@dataclass(frozen=True)
class TaskCheck:
    prompt: str
    output_model: type[BaseModel]
    verify: Callable[[BaseModel], tuple[bool, str]]
    images: tuple[ImageInput, ...] = field(default_factory=tuple)


def _requirements(out: BaseModel) -> tuple[bool, str]:
    items = [r for r in getattr(out, "requirements", []) if r.strip()]
    return (len(items) >= 2, f"Extracted {len(items)} requirements.")


def _steps(out: BaseModel) -> tuple[bool, str]:
    steps = getattr(out, "steps", [])
    return (len(steps) >= 2, f"Planned {len(steps)} steps.")


def _code(out: BaseModel) -> tuple[bool, str]:
    code = getattr(out, "code", "")
    ok = "click" in code and "Sign in" in code
    return (
        ok,
        "Produced a click on the 'Sign in' button." if ok else f"Unexpected code: {code[:80]}",
    )


def _failure(out: BaseModel) -> tuple[bool, str]:
    category = getattr(out, "category", "").strip().lower()
    ok = category in FAILURE_CATEGORIES
    return (ok, f"Classified as '{category}'." if ok else f"Unknown category '{category}'.")


def _colour(out: BaseModel) -> tuple[bool, str]:
    colour = getattr(out, "colour", "").strip().lower()
    ok = "red" in colour
    return (ok, "Recognised the red test image." if ok else f"Answered '{colour}' for a red image.")


def _locator(out: BaseModel) -> tuple[bool, str]:
    locator = getattr(out, "locator", "")
    ok = "Log in" in locator
    return (
        ok,
        f"Proposed {locator[:80]}" if ok else f"Proposal ignores the new label: {locator[:80]}",
    )


def _summary(out: BaseModel) -> tuple[bool, str]:
    summary = getattr(out, "summary", "").strip()
    return (len(summary) >= 10, "Wrote a summary." if len(summary) >= 10 else "Summary was empty.")


CHECKS: dict[TaskCategory, TaskCheck] = {
    TaskCategory.REQUIREMENT_ANALYSIS: TaskCheck(
        prompt=(
            "List the separate testable requirements in this scenario:\n"
            "<untrusted>Open the login page, sign in with the test account and check that the "
            "dashboard greets the user by name.</untrusted>"
        ),
        output_model=RequirementList,
        verify=_requirements,
    ),
    TaskCategory.TEST_PLANNING: TaskCheck(
        prompt=(
            "Write ordered browser test steps (action and target) for:\n"
            "<untrusted>Search the shop for 'laptop' and check that results appear.</untrusted>"
        ),
        output_model=StepList,
        verify=_steps,
    ),
    TaskCategory.CODE_GENERATION: TaskCheck(
        prompt=(
            "Write one line of Playwright for Python (sync API, variable `page`) that clicks the "
            "button whose accessible name is 'Sign in'. Return it in the `code` field."
        ),
        output_model=CodeSnippet,
        verify=_code,
    ),
    TaskCategory.FAILURE_ANALYSIS: TaskCheck(
        prompt=(
            "Classify this browser test failure. Use exactly one category from: "
            f"{', '.join(sorted(FAILURE_CATEGORIES))}.\n"
            "<untrusted>TimeoutError: locator('button#submit') did not become visible within "
            "30000 ms.</untrusted>"
        ),
        output_model=FailureClassification,
        verify=_failure,
    ),
    TaskCategory.VISUAL_ANALYSIS: TaskCheck(
        prompt="What single colour fills this image? Answer with one lowercase colour name.",
        output_model=ColourAnswer,
        verify=_colour,
        images=(ImageInput(data=solid_png((220, 20, 20)), mime_type="image/png"),),
    ),
    TaskCategory.TEST_REPAIR: TaskCheck(
        prompt=(
            "The locator page.locator('#login-btn') no longer matches. The button is now a "
            "<button> whose visible text is 'Log in'. Propose a replacement Playwright locator "
            "expression that uses the role and accessible name."
        ),
        output_model=LocatorProposal,
        verify=_locator,
    ),
    TaskCategory.REPORT_GENERATION: TaskCheck(
        prompt=(
            "Summarise this test run in one sentence for a release note: 3 tests passed, 1 failed "
            "(checkout total did not match the cart)."
        ),
        output_model=OneLineSummary,
        verify=_summary,
    ),
}


@dataclass(slots=True)
class TaskCheckResult:
    task: TaskCategory
    status: CheckStatus
    message: str
    provider_type: str | None = None
    model: str | None = None
    actual_model: str | None = None
    latency_ms: int | None = None
    total_tokens: int | None = None
    ai_request_id: uuid.UUID | None = None

    @property
    def label(self) -> str:
        return TASK_LABELS[self.task]


async def run_task_check(
    orchestrator: AIOrchestrator, owner_id: uuid.UUID, task: TaskCategory
) -> TaskCheckResult:
    check = CHECKS[task]
    try:
        result = await orchestrator.run_structured(
            owner_id,
            task,
            prompt=check.prompt,
            output_model=check.output_model,
            system="You are verifying that this model can perform a TestPilot task. Be brief.",
            images=check.images,
            origin="routing_check",
            max_output_tokens=2048,
        )
    except AITaskFailedError as exc:
        details = exc.details if isinstance(exc.details, dict) else {}
        return TaskCheckResult(
            task=task,
            status="error",
            message=exc.message,
            provider_type=details.get("provider"),
            model=details.get("model"),
        )

    passed, message = check.verify(result.output)
    if task == TaskCategory.VISUAL_ANALYSIS and passed:
        result.route.model.capabilities = caps.with_probe(
            result.route.model.capabilities, Capability.VISION, CapabilityStatus.SUPPORTED
        )
    record = result.record
    return TaskCheckResult(
        task=task,
        status="passed" if passed else "failed",
        message=message,
        provider_type=record.actual_provider_type,
        model=result.route.model.model_id,
        actual_model=record.actual_model,
        latency_ms=record.latency_ms,
        total_tokens=record.total_tokens,
        ai_request_id=record.id,
    )
