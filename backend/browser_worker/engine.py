"""Playwright engine: browser sessions, step execution, evidence capture and artifacts.

One session = one fresh browser context (no shared cookies or storage between runs). The step
semantics mirror the deterministic code renderer exactly, so what users review and export is
what runs here.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import logging
import re
import secrets
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    ConsoleMessage,
    Dialog,
    Locator,
    Page,
    Playwright,
    Request,
    Response,
    Route,
    WebError,
    async_playwright,
    expect,
)
from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from browser_worker import PROTOCOL_VERSION
from browser_worker.policy import NetworkPolicy, strip_query
from browser_worker.protocol import (
    BROWSERS,
    ArtifactInfo,
    ArtifactKind,
    BlockedRequest,
    BrowserLocator,
    BrowserName,
    BrowserStep,
    CloseSessionParams,
    CloseSessionResult,
    ConsoleEntry,
    ErrorCode,
    FrameParams,
    FrameResult,
    NetworkEntry,
    OpenSessionParams,
    OpenSessionResult,
    StepError,
    StepParams,
    StepResult,
    WorkerError,
    WorkerInfo,
)

logger = logging.getLogger("browser_worker")

EXPECT_DEFAULT_TIMEOUT_MS = 5_000  # Playwright's own expect() default, as in exported code
MAX_CONSOLE_ENTRIES = 300
MAX_NETWORK_ENTRIES = 2_000
MAX_SESSION_SECONDS = 30 * 60
MAX_LIVE_FRAMES = 300
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_CONSOLE_LEVELS = {"log", "info", "warning", "error", "debug"}


def _clean_message(text: str, limit: int = 1_500) -> str:
    """Playwright's message without colour codes, page snapshots or long call logs."""
    kept: list[str] = []
    call_log = 0
    for raw in _ANSI.sub("", text).splitlines():
        line = raw.rstrip()
        if not line.strip() or set(line.strip()) <= {"=", "-"}:
            continue
        if line.startswith("Call log:"):
            call_log = 1
            kept.append(line)
            continue
        if call_log:
            if not line.startswith("  - ") or call_log > 3:
                break
            call_log += 1
        kept.append(line[:300])
    return "\n".join(kept[:20])[:limit]


def _describe_locator(spec: BrowserLocator | None) -> str:
    if spec is None:
        return "the page"
    label = {"test_id": "test id", "css": "CSS", "role": spec.role or "role"}.get(
        spec.strategy, spec.strategy
    )
    nth = f" (match #{spec.nth + 1})" if spec.nth is not None else ""
    return f'{label} "{spec.value}"{nth}'


def _expectation(step: BrowserStep) -> str:
    target = _describe_locator(step.locator)
    verb = "to be" if step.match == "exact" else "to contain"
    match step.action:
        case "expect_visible":
            return f"Expected {target} to be visible."
        case "expect_hidden":
            return f"Expected {target} to be hidden."
        case "expect_text":
            return f'Expected {target} {verb} the text "{step.value}".'
        case "expect_url":
            return f'Expected the page URL {verb} "{step.value}".'
        case "expect_title":
            return f'Expected the page title {verb} "{step.value}".'
    return "Assertion failed."


def _artifact(
    root: Path, path: Path, kind: ArtifactKind, content_type: str, step_index: int | None = None
) -> ArtifactInfo:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return ArtifactInfo(
        kind=kind,
        name=path.name,
        path=path.relative_to(root).as_posix(),
        content_type=content_type,
        size_bytes=path.stat().st_size,
        sha256=digest.hexdigest(),
        step_index=step_index,
    )


@dataclass
class _Session:
    id: str
    params: OpenSessionParams
    context: BrowserContext
    page: Page
    policy: NetworkPolicy
    directory: Path
    started: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    console: list[ConsoleEntry] = field(default_factory=list)  # since the last step
    console_log: list[ConsoleEntry] = field(default_factory=list)
    console_total: int = 0
    network_log: list[NetworkEntry] = field(default_factory=list)
    network_failures: list[NetworkEntry] = field(default_factory=list)
    requests_total: int = 0
    blocked: list[BlockedRequest] = field(default_factory=list)
    request_started: dict[int, float] = field(default_factory=dict)
    sensitive: list[Locator] = field(default_factory=list)
    closed: bool = False
    current_step: int | None = None
    live_frames: int = 0

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def add_console(self, entry: ConsoleEntry) -> None:
        self.console_total += 1
        if len(self.console_log) < MAX_CONSOLE_ENTRIES:
            self.console_log.append(entry)
            self.console.append(entry)


class BrowserEngine:
    def __init__(
        self,
        artifacts_root: Path,
        *,
        max_sessions: int = 2,
        idle_timeout_seconds: float = 180.0,
        worker_id: str | None = None,
    ) -> None:
        self.artifacts_root = artifacts_root.resolve()
        self.max_sessions = max_sessions
        self.idle_timeout_seconds = idle_timeout_seconds
        self.worker_id = worker_id or f"bw-{secrets.token_hex(4)}"
        self._playwright: Playwright | None = None
        self._browsers: dict[str, Browser] = {}
        self._launch_lock = asyncio.Lock()
        self._sessions: dict[str, _Session] = {}
        self._version = importlib.metadata.version("playwright")

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()

    async def stop(self) -> None:
        for session_id in list(self._sessions):
            try:
                await self.close(CloseSessionParams(session_id=session_id))
            except Exception:
                logger.warning("Failed to close session during shutdown", exc_info=True)
        for browser in self._browsers.values():
            try:
                await browser.close()
            except PlaywrightError:
                pass
        self._browsers.clear()
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    @property
    def has_capacity(self) -> bool:
        return len(self._sessions) < self.max_sessions

    def info(self) -> WorkerInfo:
        pw = self._require_playwright()
        browsers = {name: Path(getattr(pw, name).executable_path).exists() for name in BROWSERS}
        return WorkerInfo(
            worker_id=self.worker_id,
            protocol_version=PROTOCOL_VERSION,
            playwright_version=self._version,
            browsers=browsers,
            max_sessions=self.max_sessions,
            active_sessions=len(self._sessions),
        )

    async def reap_idle(self) -> None:
        now = time.monotonic()
        for session in list(self._sessions.values()):
            idle = now - session.last_activity > self.idle_timeout_seconds
            expired = now - session.started > MAX_SESSION_SECONDS
            if (idle and not session.lock.locked()) or expired:
                logger.warning("Closing abandoned browser session %s", session.id)
                try:
                    await self.close(CloseSessionParams(session_id=session.id))
                except Exception:
                    logger.warning("Failed to reap session", exc_info=True)

    # ------------------------------------------------------------------ sessions
    async def open(self, params: OpenSessionParams) -> OpenSessionResult:
        if not self.has_capacity:
            raise WorkerError("worker.busy", "The browser worker is at capacity; try again.")
        browser = await self._browser(params.browser)
        directory = self.artifacts_root / str(params.execution_id)
        directory.mkdir(parents=True, exist_ok=True)
        capture = params.capture
        context_options: dict[str, Any] = {
            "viewport": {"width": params.viewport.width, "height": params.viewport.height},
            "accept_downloads": False,
            "service_workers": "block",  # keep every request visible to the network policy
        }
        if capture.video:
            context_options["record_video_dir"] = str(
                directory / f"{params.label or 'session'}-video-tmp"
            )
            context_options["record_video_size"] = context_options["viewport"]
        context = await browser.new_context(**context_options)
        context.set_default_timeout(params.default_timeout_ms)
        context.set_default_navigation_timeout(params.navigation_timeout_ms)
        policy = NetworkPolicy(
            params.allowed_domains, allow_private_network=params.allow_private_network
        )
        session_id = secrets.token_urlsafe(16)
        try:
            if capture.trace:
                await context.tracing.start(screenshots=True, snapshots=True, sources=False)
            page = await context.new_page()
        except PlaywrightError as exc:
            await context.close()
            raise WorkerError("browser.launch_failed", _clean_message(str(exc))) from exc
        session = _Session(
            id=session_id,
            params=params,
            context=context,
            page=page,
            policy=policy,
            directory=directory,
        )

        async def route_handler(route: Route, request: Request) -> None:
            await self._route(session, route, request)

        await context.route("**/*", route_handler)
        self._wire_events(session)
        self._sessions[session_id] = session
        return OpenSessionResult(
            session_id=session_id,
            worker_id=self.worker_id,
            browser=params.browser,
            browser_version=browser.version,
        )

    async def close(self, params: CloseSessionParams) -> CloseSessionResult:
        session = self._sessions.pop(params.session_id, None)
        if session is None:
            raise WorkerError("session.not_found", "The browser session no longer exists.")
        session.closed = True
        root, directory, capture = self.artifacts_root, session.directory, session.params.capture
        prefix = f"{session.params.label}-" if session.params.label else ""
        artifacts: list[ArtifactInfo] = []
        try:
            if capture.trace:
                trace = directory / f"{prefix}trace.zip"
                await session.context.tracing.stop(path=trace)
                artifacts.append(_artifact(root, trace, "trace", "application/zip"))
        except PlaywrightError:
            logger.warning("Could not save trace", exc_info=True)
        video = session.page.video if capture.video else None
        try:
            await session.context.close()
        except PlaywrightError:
            pass
        if video is not None:
            try:
                target = directory / f"{prefix}video.webm"
                await video.save_as(target)
                artifacts.append(_artifact(root, target, "video", "video/webm"))
            except PlaywrightError:
                logger.warning("Could not save video", exc_info=True)
            shutil.rmtree(
                directory / f"{session.params.label or 'session'}-video-tmp", ignore_errors=True
            )
        network = directory / f"{prefix}network.json"
        network.write_text(
            json.dumps([e.model_dump() for e in session.network_log], indent=1), encoding="utf-8"
        )
        artifacts.append(_artifact(root, network, "network_log", "application/json"))
        if session.console_log:
            console = directory / f"{prefix}console.json"
            console.write_text(
                json.dumps([e.model_dump() for e in session.console_log], indent=1),
                encoding="utf-8",
            )
            artifacts.append(_artifact(root, console, "console_log", "application/json"))
        return CloseSessionResult(
            artifacts=artifacts,
            requests_total=session.requests_total,
            console_total=session.console_total,
        )

    # ------------------------------------------------------------------ steps
    async def step(self, params: StepParams) -> StepResult:
        session = self._sessions.get(params.session_id)
        if session is None:
            raise WorkerError("session.not_found", "The browser session no longer exists.")
        async with session.lock:
            session.touch()
            session.current_step = params.index
            started = time.monotonic()
            error: StepError | None = None
            artifacts: list[ArtifactInfo] = []
            outer_timeout = (
                max(
                    params.step.timeout_ms or 0,
                    session.params.default_timeout_ms,
                    session.params.navigation_timeout_ms,
                )
                / 1000
                + 10
            )
            try:
                shot = await asyncio.wait_for(self._perform(session, params), outer_timeout)
                if shot is not None:
                    artifacts.append(shot)
            except TimeoutError:
                error = StepError(code="step.timeout", message="The step did not finish in time.")
            except AssertionError as exc:
                detail = _clean_message(str(exc), limit=1_200)
                error = StepError(
                    code="step.assertion_failed",
                    message=f"{_expectation(params.step)}\n{detail}",
                )
            except PlaywrightTimeoutError as exc:
                error = StepError(code="step.timeout", message=_clean_message(str(exc)))
            except PlaywrightError as exc:
                error = self._classify(session, params, exc)
            except Exception:
                logger.exception("Unexpected error while executing a step")
                error = StepError(code="internal", message="The browser worker hit an error.")
            duration_ms = int((time.monotonic() - started) * 1000)
            capture = session.params.capture.screenshots
            if not session.closed and (
                capture == "every_step" or (error is not None and capture == "on_failure")
            ):
                frame = await self._frame(session, params.index)
                if frame is not None:
                    artifacts.append(frame)
            url, title = await self._location(session)
            session.touch()
            result = StepResult(
                index=params.index,
                status="failed" if error else "passed",
                duration_ms=duration_ms,
                url=url,
                title=title,
                error=error,
                artifacts=artifacts,
                console=session.console,
                network_failures=session.network_failures,
                blocked=session.blocked,
            )
            session.console, session.network_failures, session.blocked = [], [], []
            return result

    async def _perform(self, session: _Session, params: StepParams) -> ArtifactInfo | None:
        step, page = params.step, session.page
        timeout = float(step.timeout_ms) if step.timeout_ms else None
        expect_timeout = float(step.timeout_ms or EXPECT_DEFAULT_TIMEOUT_MS)
        value = step.value or ""
        locator = self._locator(page, step.locator) if step.locator else None
        match step.action:
            case "goto":
                url = session.params.base_url + value if value.startswith("/") else value
                await page.goto(url, timeout=timeout)
            case "click":
                assert locator is not None
                await locator.click(timeout=timeout)
            case "fill":
                assert locator is not None
                await locator.fill(value, timeout=timeout)
                if params.sensitive:
                    session.sensitive.append(locator)
            case "select_option":
                assert locator is not None
                await locator.select_option(value, timeout=timeout)
                if params.sensitive:
                    session.sensitive.append(locator)
            case "check":
                assert locator is not None
                await locator.check(timeout=timeout)
            case "uncheck":
                assert locator is not None
                await locator.uncheck(timeout=timeout)
            case "press":
                if locator is not None:
                    await locator.press(value, timeout=timeout)
                else:
                    await page.keyboard.press(value)
            case "wait_for":
                assert locator is not None
                await locator.wait_for(state=step.state or "visible", timeout=timeout)
            case "expect_visible":
                assert locator is not None
                await expect(locator).to_be_visible(timeout=expect_timeout)
            case "expect_hidden":
                assert locator is not None
                await expect(locator).to_be_hidden(timeout=expect_timeout)
            case "expect_text":
                assert locator is not None
                if step.match == "exact":
                    await expect(locator).to_have_text(value, timeout=expect_timeout)
                else:
                    await expect(locator).to_contain_text(value, timeout=expect_timeout)
            case "expect_url" | "expect_title":
                expected: str | re.Pattern[str] = (
                    value if step.match == "exact" else re.compile(re.escape(value))
                )
                if step.action == "expect_url":
                    await expect(page).to_have_url(expected, timeout=expect_timeout)
                else:
                    await expect(page).to_have_title(expected, timeout=expect_timeout)
            case "screenshot":
                name = params.screenshot_name or f"step-{params.index:03d}"
                path = session.directory / f"shot-{params.index:03d}-{name}.png"
                await page.screenshot(path=path, full_page=True, mask=session.sensitive)
                return _artifact(self.artifacts_root, path, "screenshot", "image/png", params.index)
        return None

    @staticmethod
    def _locator(page: Page, spec: BrowserLocator) -> Locator:
        value, exact = spec.value, spec.exact or None
        match spec.strategy:
            case "role":
                locator = page.get_by_role(spec.role, name=value, exact=exact)  # type: ignore[arg-type]
            case "label":
                locator = page.get_by_label(value, exact=exact)
            case "text":
                locator = page.get_by_text(value, exact=exact)
            case "placeholder":
                locator = page.get_by_placeholder(value, exact=exact)
            case "test_id":
                locator = page.get_by_test_id(value)
            case _:
                locator = page.locator(value)
        return locator.nth(spec.nth) if spec.nth is not None else locator

    def _classify(self, session: _Session, params: StepParams, exc: PlaywrightError) -> StepError:
        message = _clean_message(str(exc))
        if session.closed:
            return StepError(code="step.error", message="The browser session was closed.")
        code: ErrorCode = "step.error"
        if params.step.action == "goto":
            blocked = next((b for b in reversed(session.blocked) if b.navigation), None)
            if blocked is not None:
                return StepError(
                    code="step.navigation_blocked",
                    message=f"Navigation to {blocked.url} was blocked: {blocked.reason}",
                )
            code = "step.navigation_failed"
        elif "strict mode violation" in message or "not an <input>" in message:
            code = "step.element_error"
        return StepError(code=code, message=message)

    async def frame(self, params: FrameParams) -> FrameResult:
        """A throttled in-progress frame for the live preview.

        Deliberately does not take the session lock: it is called while a step is running.
        """
        session = self._sessions.get(params.session_id)
        if session is None or session.closed or session.page.is_closed():
            raise WorkerError("session.not_found", "The browser session no longer exists.")
        if session.live_frames >= MAX_LIVE_FRAMES:
            return FrameResult(step_index=session.current_step)
        session.live_frames += 1
        prefix = f"{session.params.label}-" if session.params.label else ""
        path = session.directory / f"{prefix}live-{session.live_frames:04d}.jpg"
        try:
            await session.page.screenshot(
                path=path, type="jpeg", quality=50, mask=session.sensitive, timeout=3_000
            )
        except PlaywrightError:
            return FrameResult(step_index=session.current_step)
        artifact = _artifact(self.artifacts_root, path, "frame", "image/jpeg", session.current_step)
        return FrameResult(
            artifact=artifact, url=strip_query(session.page.url), step_index=session.current_step
        )

    async def _frame(self, session: _Session, index: int) -> ArtifactInfo | None:
        path = session.directory / f"step-{index:03d}.jpg"
        try:
            await session.page.screenshot(
                path=path, type="jpeg", quality=70, mask=session.sensitive, timeout=5_000
            )
        except PlaywrightError:
            return None
        return _artifact(self.artifacts_root, path, "screenshot", "image/jpeg", index)

    @staticmethod
    async def _location(session: _Session) -> tuple[str | None, str | None]:
        if session.closed or session.page.is_closed():
            return None, None
        url = strip_query(session.page.url)
        try:
            title = await asyncio.wait_for(session.page.title(), 2)
        except (TimeoutError, PlaywrightError):
            title = None
        return url, (title or "")[:300] or None

    # ------------------------------------------------------------------ evidence
    async def _route(self, session: _Session, route: Route, request: Request) -> None:
        try:
            top_level = request.is_navigation_request() and request.frame.parent_frame is None
        except PlaywrightError:
            top_level = request.resource_type == "document"
        decision = await session.policy.check(request.url, top_level_navigation=top_level)
        try:
            if decision.allowed:
                await route.continue_()
            else:
                session.blocked.append(
                    BlockedRequest(
                        url=strip_query(request.url), reason=decision.reason, navigation=top_level
                    )
                )
                await route.abort("blockedbyclient")
        except PlaywrightError:
            pass  # the context is closing

    def _wire_events(self, session: _Session) -> None:
        context = session.context

        def on_console(message: ConsoleMessage) -> None:
            level = message.type if message.type in _CONSOLE_LEVELS else "log"
            location = message.location.get("url") if message.location else None
            session.add_console(
                ConsoleEntry(
                    level=level,
                    text=message.text[:1000],
                    url=strip_query(location) if location else None,
                )
            )

        def on_web_error(error: WebError) -> None:
            session.add_console(ConsoleEntry(level="pageerror", text=str(error.error)[:1000]))

        async def on_dialog(dialog: Dialog) -> None:
            session.add_console(
                ConsoleEntry(level="dialog", text=f"{dialog.type}: {dialog.message}"[:1000])
            )
            try:
                await dialog.dismiss()
            except PlaywrightError:
                pass

        def on_request(request: Request) -> None:
            session.requests_total += 1
            session.request_started[id(request)] = time.monotonic()

        def record(request: Request, status: int | None, failure: str | None) -> None:
            started = session.request_started.pop(id(request), None)
            entry = NetworkEntry(
                method=request.method[:10],
                url=strip_query(request.url),
                resource_type=request.resource_type[:30],
                status=status,
                failure=failure[:200] if failure else None,
                duration_ms=int((time.monotonic() - started) * 1000) if started else None,
            )
            if len(session.network_log) < MAX_NETWORK_ENTRIES:
                session.network_log.append(entry)
            blocked = any(b.url == entry.url for b in session.blocked)
            if (failure and not blocked) or (status is not None and status >= 400):
                if len(session.network_failures) < 50:
                    session.network_failures.append(entry)

        def on_response(response: Response) -> None:
            record(response.request, response.status, None)

        def on_failed(request: Request) -> None:
            record(request, None, request.failure or "failed")

        context.on("console", on_console)
        context.on("weberror", on_web_error)
        context.on("dialog", on_dialog)
        context.on("request", on_request)
        context.on("response", on_response)
        context.on("requestfailed", on_failed)

    # ------------------------------------------------------------------ browsers
    def _require_playwright(self) -> Playwright:
        if self._playwright is None:
            raise WorkerError("internal", "The browser engine is not started.")
        return self._playwright

    async def _browser(self, name: BrowserName) -> Browser:
        async with self._launch_lock:
            browser = self._browsers.get(name)
            if browser is not None and browser.is_connected():
                return browser
            browser_type = getattr(self._require_playwright(), name)
            if not Path(browser_type.executable_path).exists():  # noqa: ASYNC240 - one stat
                raise WorkerError(
                    "browser.unavailable",
                    f"{name.capitalize()} is not installed in this browser worker "
                    f"(install it with `playwright install {name}`).",
                )
            try:
                launched: Browser = await browser_type.launch(headless=True)
            except PlaywrightError as exc:
                raise WorkerError("browser.launch_failed", _clean_message(str(exc))) from exc
            self._browsers[name] = launched
            return launched
