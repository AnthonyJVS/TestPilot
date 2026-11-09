"""Commands and results exchanged between the orchestrator and the browser worker.

Everything crossing the boundary is validated here, on both sides. Step values arrive already
resolved (test data substituted); values typed from secrets are flagged ``sensitive`` so the
worker masks those fields in screenshots and never echoes them back.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

BrowserName = Literal["chromium", "firefox", "webkit"]
BROWSERS: tuple[BrowserName, ...] = ("chromium", "firefox", "webkit")

StepAction = Literal[
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

# "frame": throttled in-progress frames for the live Browser Preview (not step evidence).
ArtifactKind = Literal["screenshot", "frame", "trace", "video", "network_log", "console_log"]

# Stable error codes the orchestrator maps to user-facing results.
ErrorCode = Literal[
    "browser.unavailable",
    "browser.launch_failed",
    "session.not_found",
    "worker.busy",
    "worker.timeout",
    "step.timeout",
    "step.assertion_failed",
    "step.navigation_blocked",
    "step.navigation_failed",
    "step.element_error",
    "step.error",
    "request.invalid",
    "internal",
]

# Redis queues (see server.py).
REQUEST_QUEUE = "bw:requests"
REPLY_PREFIX = "bw:reply:"


def worker_queue(worker_id: str) -> str:
    return f"bw:worker:{worker_id}"


_SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BrowserLocator(_Model):
    strategy: Literal["role", "label", "text", "placeholder", "test_id", "css"]
    value: str = Field(min_length=1, max_length=300)
    role: str | None = Field(default=None, max_length=40)
    exact: bool = False
    nth: int | None = Field(default=None, ge=0, le=50)


class BrowserStep(_Model):
    """One plan step with test data already substituted."""

    action: StepAction
    locator: BrowserLocator | None = None
    value: str | None = Field(default=None, max_length=4000)
    match: Literal["contains", "exact"] | None = None
    state: Literal["visible", "hidden", "attached", "detached"] | None = None
    timeout_ms: int | None = Field(default=None, ge=100, le=120_000)


class CaptureOptions(_Model):
    screenshots: Literal["every_step", "on_failure", "off"] = "every_step"
    trace: bool = True
    video: bool = False


class Viewport(_Model):
    width: int = Field(default=1280, ge=320, le=3840)
    height: int = Field(default=800, ge=240, le=2160)


class OpenSessionParams(_Model):
    execution_id: uuid.UUID
    browser: BrowserName = "chromium"
    base_url: str = Field(max_length=500)
    allowed_domains: list[str] = Field(min_length=1, max_length=50)
    allow_private_network: bool = False
    viewport: Viewport = Viewport()
    capture: CaptureOptions = CaptureOptions()
    default_timeout_ms: int = Field(default=10_000, ge=1_000, le=120_000)
    navigation_timeout_ms: int = Field(default=30_000, ge=1_000, le=120_000)
    # Prefix for session-level artifacts when one execution opens several sessions.
    label: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,19}$")

    @field_validator("base_url")
    @classmethod
    def _http(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("base_url must be http(s)")
        return value.rstrip("/")


class StepParams(_Model):
    session_id: str = Field(min_length=8, max_length=64)
    index: int = Field(ge=0, le=999)
    step: BrowserStep
    sensitive: bool = False
    screenshot_name: str | None = None

    @field_validator("screenshot_name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is not None and not _SAFE_NAME.match(value):
            raise ValueError("invalid screenshot name")
        return value


class FrameParams(_Model):
    session_id: str = Field(min_length=8, max_length=64)


class FrameResult(_Model):
    artifact: ArtifactInfo | None = None
    url: str | None = Field(default=None, max_length=500)
    step_index: int | None = None


class CloseSessionParams(_Model):
    session_id: str = Field(min_length=8, max_length=64)


class ArtifactInfo(_Model):
    kind: ArtifactKind
    name: str = Field(max_length=200)
    # Relative to the artifacts root: "<execution_id>/<file>". Never absolute.
    path: str = Field(max_length=300)
    content_type: str = Field(max_length=100)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)
    step_index: int | None = None


class ConsoleEntry(_Model):
    level: Literal["log", "info", "warning", "error", "debug", "pageerror", "dialog"]
    text: str = Field(max_length=1000)
    url: str | None = Field(default=None, max_length=500)


class NetworkEntry(_Model):
    method: str = Field(max_length=10)
    url: str = Field(max_length=500)  # query string and fragment removed
    resource_type: str = Field(max_length=30)
    status: int | None = None
    failure: str | None = Field(default=None, max_length=200)
    duration_ms: int | None = None


class BlockedRequest(_Model):
    url: str = Field(max_length=500)
    reason: str = Field(max_length=200)
    navigation: bool = False


class StepError(_Model):
    code: ErrorCode
    message: str = Field(max_length=2000)


class OpenSessionResult(_Model):
    session_id: str
    worker_id: str
    browser: BrowserName
    browser_version: str


class StepResult(_Model):
    index: int
    status: Literal["passed", "failed"]
    duration_ms: int
    url: str | None = None
    title: str | None = Field(default=None, max_length=300)
    error: StepError | None = None
    artifacts: list[ArtifactInfo] = Field(default_factory=list)
    console: list[ConsoleEntry] = Field(default_factory=list)
    network_failures: list[NetworkEntry] = Field(default_factory=list)
    blocked: list[BlockedRequest] = Field(default_factory=list)
    # Accessibility tree of the page when the step failed (roles, names, texts): evidence for
    # failure analysis. Field values may appear; the orchestrator scrubs secret values.
    page_snapshot: str | None = Field(default=None, max_length=12_000)


class CloseSessionResult(_Model):
    artifacts: list[ArtifactInfo] = Field(default_factory=list)
    requests_total: int = 0
    console_total: int = 0


class WorkerInfo(_Model):
    worker_id: str
    protocol_version: int
    playwright_version: str
    browsers: dict[str, bool]
    max_sessions: int
    active_sessions: int


Method = Literal["info", "open", "step", "frame", "close"]


class RpcRequest(_Model):
    id: str = Field(min_length=8, max_length=64)
    method: Method
    params: dict[str, Any] = Field(default_factory=dict)
    reply_to: str = Field(max_length=100)
    deadline: float  # unix time; expired requests are dropped unanswered


class RpcError(_Model):
    code: ErrorCode
    message: str = Field(max_length=2000)


class RpcResponse(_Model):
    id: str
    ok: bool
    result: dict[str, Any] | None = None
    error: RpcError | None = None


class WorkerError(Exception):
    """A typed failure raised by the engine and carried across the RPC boundary."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.message = message


FrameResult.model_rebuild()
