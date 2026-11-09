"""Execution building blocks: network policy, test data, secret scrubbing, worker RPC, notifiers."""

from __future__ import annotations

import ast
import asyncio
import uuid
from pathlib import Path
from typing import Any

import fakeredis
import pytest

from app.core.config import Settings
from app.domain.test_plan import TestPlan
from app.services.execution.browser_client import RedisBrowserClient
from app.services.execution.events import InMemoryNotifier, RedisNotifier
from app.services.execution.test_data import (
    MissingVariablesError,
    SecretScrubber,
    Variable,
    build_commands,
    missing_variables,
)
from browser_worker.policy import NetworkPolicy, classify_address, host_allowed, strip_query
from browser_worker.protocol import (
    CloseSessionParams,
    CloseSessionResult,
    OpenSessionParams,
    OpenSessionResult,
    StepParams,
    StepResult,
    WorkerError,
    WorkerInfo,
)
from browser_worker.server import RedisWorkerServer

BACKEND = Path(__file__).resolve().parents[2]

# ------------------------------------------------------------------ network policy


@pytest.mark.parametrize(
    ("address", "kind"),
    [
        ("93.184.216.34", "public"),
        ("2606:4700::6810:84e5", "public"),
        ("127.0.0.1", "private"),
        ("10.1.2.3", "private"),
        ("192.168.0.10", "private"),
        ("::1", "private"),
        ("::ffff:127.0.0.1", "private"),
        ("224.0.0.1", "private"),
        ("169.254.169.254", "link_local"),
        ("fe80::1", "link_local"),
        ("fd00:ec2::254", "link_local"),
    ],
)
def test_address_classification(address: str, kind: str) -> None:
    assert classify_address(address) == kind


def test_host_matching_and_url_stripping() -> None:
    assert host_allowed("shop.example.com", ["shop.example.com"])
    assert host_allowed("a.cdn.example.com", ["*.cdn.example.com"])
    assert not host_allowed("cdn.example.com", ["*.cdn.example.com"])
    assert not host_allowed("evil-example.com", ["example.com"])
    assert strip_query("https://u:p@x.com:8443/a/b?token=1#f") == "https://x.com:8443/a/b"
    assert strip_query("data:text/plain,hello") == "data:"


async def test_policy_decisions() -> None:
    strict = NetworkPolicy(["example.com", "127.0.0.1"], allow_private_network=False)
    assert (await strict.check("data:,x", top_level_navigation=True)).allowed
    assert not (await strict.check("file:///etc/passwd", top_level_navigation=False)).allowed
    outside = await strict.check("https://other.org/", top_level_navigation=True)
    assert not outside.allowed and "allowed domains" in outside.reason
    # Sub-resources may come from other public hosts, but never from private ones.
    assert (await strict.check("https://93.184.216.34/x.js", top_level_navigation=False)).allowed
    assert not (await strict.check("http://127.0.0.1/", top_level_navigation=True)).allowed
    assert not (await strict.check("http://localhost/", top_level_navigation=False)).allowed

    relaxed = NetworkPolicy(["127.0.0.1"], allow_private_network=True)
    assert (await relaxed.check("http://127.0.0.1:3000/", top_level_navigation=True)).allowed
    # Cloud metadata stays blocked even when private targets are allowed.
    metadata = await relaxed.check("http://169.254.169.254/latest", top_level_navigation=False)
    assert not metadata.allowed and "link-local" in metadata.reason
    named = await relaxed.check("http://metadata.google.internal/", top_level_navigation=False)
    assert not named.allowed


# ------------------------------------------------------------------ test data


def _plan() -> TestPlan:
    return TestPlan.model_validate(
        {
            "name": "Login",
            "test_data": [
                {"name": "LOGIN_EMAIL", "kind": "env"},
                {"name": "PASSWORD", "kind": "secret"},
            ],
            "steps": [
                {"action": "goto", "description": "Open", "value": "/login"},
                {
                    "action": "fill",
                    "description": "Email",
                    "locator": {"strategy": "label", "value": "Email"},
                    "value": "{{env.LOGIN_EMAIL}}",
                },
                {
                    "action": "fill",
                    "description": "Password",
                    "locator": {"strategy": "label", "value": "Password"},
                    "value": "{{ secret.PASSWORD }}",
                },
                {"action": "screenshot", "description": "Shot", "value": "signed-in"},
            ],
        }
    )


def test_commands_resolve_placeholders_and_flag_secrets() -> None:
    variables = {
        "LOGIN_EMAIL": Variable("LOGIN_EMAIL", "qa@example.com", False),
        "PASSWORD": Variable("PASSWORD", "hunter2-secret", True),
    }
    commands = build_commands(_plan(), variables)
    assert [c.step.value for c in commands] == [
        "/login",
        "qa@example.com",
        "hunter2-secret",
        "signed-in",
    ]
    assert [c.sensitive for c in commands] == [False, False, True, False]
    assert commands[3].screenshot_name == "signed-in"


def test_missing_or_mismatched_variables_are_reported() -> None:
    plan = _plan()
    assert missing_variables(plan, {}) == ["{{env.LOGIN_EMAIL}}", "{{secret.PASSWORD}}"]
    # A plain variable cannot stand in for a secret (it would be shown in screenshots).
    wrong_kind = {
        "LOGIN_EMAIL": Variable("LOGIN_EMAIL", "a", False),
        "PASSWORD": Variable("PASSWORD", "b", False),
    }
    with pytest.raises(MissingVariablesError) as error:
        build_commands(plan, wrong_kind)
    assert error.value.names == ["{{secret.PASSWORD}}"]


def test_scrubber_replaces_secret_values_everywhere() -> None:
    scrubber = SecretScrubber(
        {
            "TOKEN": Variable("TOKEN", "abc123token", True),
            "SHORT": Variable("SHORT", "ab", True),  # too short to scrub safely
            "EMAIL": Variable("EMAIL", "qa@example.com", False),
        }
    )
    data: dict[str, Any] = {
        "message": "typed abc123token into field",
        "nested": [{"text": "x abc123token y"}, 3],
    }
    assert scrubber.data(data) == {
        "message": "typed [secret:TOKEN] into field",
        "nested": [{"text": "x [secret:TOKEN] y"}, 3],
    }
    assert scrubber.text("qa@example.com ab") == "qa@example.com ab"


# ------------------------------------------------------------------ worker RPC over Redis


class FakeEngine:
    worker_id = "bw-test"
    has_capacity = True

    def __init__(self) -> None:
        self.steps: list[StepParams] = []

    def info(self) -> WorkerInfo:
        return WorkerInfo(
            worker_id=self.worker_id,
            protocol_version=1,
            playwright_version="test",
            browsers={"chromium": True, "firefox": False, "webkit": False},
            max_sessions=1,
            active_sessions=0,
        )

    async def open(self, params: OpenSessionParams) -> OpenSessionResult:
        if params.browser == "webkit":
            raise WorkerError("browser.unavailable", "Webkit is not installed.")
        return OpenSessionResult(
            session_id="session-1234",
            worker_id=self.worker_id,
            browser="chromium",
            browser_version="1.0",
        )

    async def step(self, params: StepParams) -> StepResult:
        self.steps.append(params)
        return StepResult(index=params.index, status="passed", duration_ms=5)

    async def close(self, params: CloseSessionParams) -> CloseSessionResult:
        return CloseSessionResult(requests_total=3)

    async def reap_idle(self) -> None:
        return None


async def test_redis_rpc_round_trip_routes_sessions_to_their_worker() -> None:
    server_state = fakeredis.FakeServer()
    worker_redis = fakeredis.FakeAsyncRedis(server=server_state, decode_responses=True)
    api_redis = fakeredis.FakeAsyncRedis(server=server_state, decode_responses=True)
    engine = FakeEngine()
    server = RedisWorkerServer(worker_redis, engine)  # type: ignore[arg-type]
    serving = asyncio.create_task(server.serve())
    client = RedisBrowserClient(api_redis)
    try:
        info = await client.info()
        assert info.browsers["chromium"] is True
        params = OpenSessionParams(
            execution_id=uuid.uuid4(), base_url="https://shop.example.com", allowed_domains=["x"]
        )
        opened = await client.open(params)
        assert opened.worker_id == "bw-test"
        step = StepParams(
            session_id=opened.session_id,
            index=0,
            step={"action": "goto", "value": "/"},  # type: ignore[arg-type]
        )
        result = await client.step(step, worker_id=opened.worker_id, wait_seconds=5)
        assert result.status == "passed" and engine.steps[0].index == 0
        closed = await client.close(
            CloseSessionParams(session_id=opened.session_id), worker_id=opened.worker_id
        )
        assert closed.requests_total == 3
        with pytest.raises(WorkerError) as error:
            await client.open(params.model_copy(update={"browser": "webkit"}))
        assert error.value.code == "browser.unavailable"
    finally:
        server.stop()
        await serving
    # Nobody listening: the client gives up with a typed timeout instead of hanging.
    with pytest.raises(WorkerError) as timeout:
        await client.step(step, worker_id="bw-gone", wait_seconds=1)
    assert timeout.value.code == "worker.timeout"


async def test_notifiers_wake_subscribers() -> None:
    execution_id = uuid.uuid4()
    memory = InMemoryNotifier()
    async with memory.subscribe(execution_id) as subscription:
        assert await subscription.wait(0.01) is False
        await memory.publish(execution_id)
        assert await subscription.wait(1) is True

    redis = RedisNotifier(fakeredis.FakeAsyncRedis(decode_responses=True))
    async with redis.subscribe(execution_id) as subscription:
        await redis.publish(execution_id)
        assert await subscription.wait(1) is True


# ------------------------------------------------------------------ configuration and boundaries


def test_production_requires_isolated_execution() -> None:
    base: dict[str, Any] = {
        "app_env": "production",
        "jwt_secret": "x" * 40,
        "redis_url": "redis://redis:6379/0",
        "database_url": "postgresql+asyncpg://u:p@db/x",
        "encryption_keys": "v1:" + "A" * 43,
    }
    with pytest.raises(ValueError, match="EXECUTION_MODE=celery"):
        Settings(_env_file=None, **base)  # type: ignore[call-arg]
    ok = Settings(
        _env_file=None,  # type: ignore[call-arg]
        **base,
        execution_mode="celery",
        browser_transport="redis",
    )
    assert ok.browser_transport == "redis"
    with pytest.raises(ValueError, match="need REDIS_URL"):
        Settings(_env_file=None, browser_transport="redis")  # type: ignore[call-arg]


def _imports(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_browser_worker_never_imports_the_app() -> None:
    """The worker image ships without the app: no database models, settings or AI keys."""
    for path in (BACKEND / "browser_worker").glob("*.py"):
        offending = {m for m in _imports(path) if m == "app" or m.startswith("app.")}
        assert not offending, f"{path.name} imports {offending}"


def test_api_does_not_import_playwright_at_module_level() -> None:
    """Playwright is only needed where browsers run; the API image does not install it."""
    for path in (BACKEND / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:  # module level only; lazy imports inside functions are fine
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert not name.startswith(("playwright", "browser_worker.engine")), path
