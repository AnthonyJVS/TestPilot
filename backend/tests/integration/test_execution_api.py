"""Real test runs end to end: API → inline job → orchestrator → Playwright (Chromium) → events.

The target is a local fixture site served on 127.0.0.1, so these tests allow private networks
explicitly (except where the network policy itself is under test).
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.conftest import ClientFactory, bearer, register

API = "/api/v1"
SITE = Path(__file__).resolve().parents[1] / "fixtures" / "site"
SECRET = "tok-9f8e7d6c5b4a"


def _chromium_installed() -> bool:
    # Checked in a subprocess so Playwright's own event loop never mixes with the test loop.
    check = "; ".join(
        [
            "import pathlib, sys",
            "from playwright.sync_api import sync_playwright",
            "p = sync_playwright().start()",
            "ok = pathlib.Path(p.chromium.executable_path).exists()",
            "p.stop()",
            "sys.exit(0 if ok else 1)",
        ]
    )
    try:
        result = subprocess.run([sys.executable, "-c", check], timeout=60, check=False)  # noqa: S603
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


pytestmark = pytest.mark.skipif(not _chromium_installed(), reason="Chromium is not installed")


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture(scope="module")
def site_url() -> Iterator[str]:
    handler = functools.partial(_QuietHandler, directory=str(SITE))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


Ctx = tuple[httpx.AsyncClient, dict[str, str]]


@pytest.fixture
async def runner(client_factory: ClientFactory, tmp_path: Path) -> AsyncIterator[Ctx]:
    async with client_factory(
        browser_allow_private_network=True, artifacts_dir=str(tmp_path / "artifacts")
    ) as client:
        token = (await register(client)).json()["access_token"]
        yield client, bearer(token)


def step(action: str, description: str, **fields: Any) -> dict[str, Any]:
    return {"action": action, "description": description, **fields}


def locator(strategy: str, value: str, **fields: Any) -> dict[str, Any]:
    return {"strategy": strategy, "value": value, **fields}


LOGIN_STEPS = [
    step("goto", "Open the app", value="/index.html"),
    step("fill", "Enter the email", locator=locator("label", "Email"), value="{{env.LOGIN_EMAIL}}"),
    step(
        "fill",
        "Enter the API token",
        locator=locator("label", "API token"),
        value="{{secret.API_TOKEN}}",
    ),
    step("click", "Sign in", locator=locator("role", "Sign in", role="button")),
    step(
        "expect_text",
        "Greeting shows the email",
        locator=locator("test_id", "greeting"),
        value="Signed in as {{env.LOGIN_EMAIL}}",
    ),
    step(
        "fill",
        "Type a todo",
        locator=locator("placeholder", "What needs to be done?"),
        value="Buy milk",
    ),
    step("press", "Submit it", value="Enter"),
    step(
        "expect_text",
        "The todo is listed",
        locator=locator("test_id", "todo-title"),
        value="Buy milk",
        match="exact",
    ),
]


async def approved_version(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    base_url: str,
    steps: list[dict[str, Any]],
    *,
    with_data: bool = True,
) -> tuple[dict[str, Any], str]:
    project = (
        await client.post(
            f"{API}/projects",
            headers=headers,
            json={"name": f"Fixture {uuid.uuid4().hex[:6]}", "base_url": base_url},
        )
    ).json()
    env_id = project["environments"][0]["id"]
    if with_data:
        for name, value, secret in (
            ("LOGIN_EMAIL", "ada@example.com", False),
            ("API_TOKEN", SECRET, True),
        ):
            response = await client.put(
                f"{API}/environments/{env_id}/variables/{name}",
                headers=headers,
                json={"value": value, "is_secret": secret},
            )
            assert response.status_code == 200, response.text
    suites = (await client.get(f"{API}/projects/{project['id']}/suites", headers=headers)).json()
    case = (
        await client.post(
            f"{API}/projects/{project['id']}/cases",
            headers=headers,
            json={"suite_id": suites[0]["id"], "name": "Sign in and add a todo"},
        )
    ).json()
    test_data = [
        {"name": "LOGIN_EMAIL", "kind": "env"},
        {"name": "API_TOKEN", "kind": "secret"},
    ]
    uses = " ".join(str(s.get("value")) for s in steps)
    plan = {
        "name": "Sign in and add a todo",
        "test_data": [d for d in test_data if d["name"] in uses],
        "steps": steps,
    }
    draft = await client.post(
        f"{API}/cases/{case['id']}/plans", headers=headers, json={"plan": plan}
    )
    assert draft.status_code == 201, draft.text
    plan_id = draft.json()["latest_plan"]["id"]
    approved = await client.post(f"{API}/plans/{plan_id}/approve", headers=headers)
    assert approved.status_code == 201, approved.text
    return project, approved.json()["id"]


async def wait_finished(
    client: httpx.AsyncClient, headers: dict[str, str], execution_id: str, seconds: float = 60
) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        execution: dict[str, Any] = (
            await client.get(f"{API}/executions/{execution_id}", headers=headers)
        ).json()
        if execution["status"] not in ("queued", "running"):
            return execution
        await asyncio.sleep(0.2)
    raise AssertionError("run did not finish in time")


async def test_real_run_passes_with_events_artifacts_and_no_secret_leaks(
    runner: Ctx, site_url: str
) -> None:
    client, headers = runner
    _, version_id = await approved_version(client, headers, site_url, LOGIN_STEPS)

    started = await client.post(f"{API}/versions/{version_id}/run", headers=headers, json={})
    assert started.status_code == 202, started.text
    assert started.json()["status"] in ("queued", "running")
    run = await wait_finished(client, headers, started.json()["id"])

    assert run["status"] == "passed", run
    test = run["test"]
    assert test["steps_passed"] == test["steps_total"] == len(LOGIN_STEPS)
    assert all(s["status"] == "passed" and s["duration_ms"] is not None for s in test["steps"])
    assert test["browser"] == "chromium" and test["browser_version"]
    assert run["isolated"] is False
    # Secrets switch traces/video off and say so.
    assert run["capture"] == {"screenshots": "every_step", "trace": False, "video": False}
    assert any("secret" in note for note in run["notes"])

    kinds = sorted({a["kind"] for a in run["artifacts"]})
    assert kinds == ["console_log", "network_log", "screenshot"]
    frames = [a for a in run["artifacts"] if a["kind"] == "screenshot"]
    assert len(frames) == len(LOGIN_STEPS)

    events = (await client.get(f"{API}/executions/{run['id']}/events", headers=headers)).json()
    seqs = [e["seq"] for e in events]
    assert seqs == list(range(1, len(events) + 1))
    types = [e["type"] for e in events]
    assert types[:3] == ["execution.created", "execution.queued", "execution.started"]
    assert types[-1] == "execution.completed"
    assert types.count("browser.step.passed") == len(LOGIN_STEPS)
    assert types.count("browser.frame") == len(LOGIN_STEPS)
    nodes = [(e["type"], e["node_id"]) for e in events if e["category"] == "node"]
    assert ("node.completed", "launch_browser") in nodes
    assert ("node.completed", "execute_test") in nodes
    assert ("node.completed", "collect_artifacts") in nodes
    messages = " | ".join(e["message"] for e in events)
    assert "fixture error message" in messages  # console capture
    assert any(e["type"] == "browser.network.failed" and e["data"]["status"] == 404 for e in events)
    # The page's request to the cloud metadata address is blocked even with private networks on.
    blocked = [e for e in events if e["type"] == "browser.request.blocked"]
    assert blocked and "169.254.169.254" in blocked[0]["data"]["url"]

    # The secret value appears nowhere: not in events, run details or the logs saved on disk.
    assert SECRET not in str(events) and SECRET not in str(run)
    for artifact in run["artifacts"]:
        if artifact["kind"] in ("console_log", "network_log"):
            body = await client.get(f"{API}/artifacts/{artifact['id']}/content", headers=headers)
            assert body.status_code == 200 and SECRET not in body.text

    frame = await client.get(f"{API}/artifacts/{frames[0]['id']}/content", headers=headers)
    assert frame.status_code == 200
    assert frame.headers["content-type"] == "image/jpeg"
    assert frame.content[:3] == b"\xff\xd8\xff"

    history = (await client.get(f"{API}/executions", headers=headers)).json()
    assert [h["id"] for h in history] == [run["id"]]
    assert history[0]["steps_passed"] == len(LOGIN_STEPS)

    # SSE: a finished run replays every event, then ends.
    stream = await client.get(f"{API}/executions/{run['id']}/events/stream", headers=headers)
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert stream.text.count("\nevent: ") + stream.text.startswith("event: ") >= len(events)
    assert "event: execution.completed" in stream.text and "event: end" in stream.text
    resumed = await client.get(
        f"{API}/executions/{run['id']}/events/stream",
        headers={**headers, "Last-Event-ID": str(len(events) - 1)},
    )
    assert "event: execution.started" not in resumed.text
    assert f"id: {len(events)}\n" in resumed.text


async def test_failing_assertion_marks_run_failed_and_skips_remaining_steps(
    runner: Ctx, site_url: str
) -> None:
    client, headers = runner
    steps = [
        step("goto", "Open the app", value="/index.html"),
        step("expect_title", "Title is wrong on purpose", value="Something else", timeout_ms=500),
        step("click", "Never runs", locator=locator("role", "Sign in", role="button")),
    ]
    _, version_id = await approved_version(client, headers, site_url, steps, with_data=False)
    started = await client.post(
        f"{API}/versions/{version_id}/run", headers=headers, json={"trace": True}
    )
    run = await wait_finished(client, headers, started.json()["id"])

    assert run["status"] == "failed"
    assert run["error_code"] == "step.assertion_failed"
    assert [s["status"] for s in run["test"]["steps"]] == ["passed", "failed", "skipped"]
    failed = run["test"]["steps"][1]
    assert failed["error_code"] == "step.assertion_failed"
    assert "Something else" in failed["error_message"]
    assert "trace" in {a["kind"] for a in run["artifacts"]}  # no secrets → trace kept
    trace = next(a for a in run["artifacts"] if a["kind"] == "trace")
    download = await client.get(f"{API}/artifacts/{trace['id']}/content", headers=headers)
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith("attachment")
    assert download.content[:2] == b"PK"


async def test_private_targets_are_blocked_unless_allowed(
    client_factory: ClientFactory, tmp_path: Path, site_url: str
) -> None:
    async with client_factory(artifacts_dir=str(tmp_path / "a")) as client:
        headers = bearer((await register(client)).json()["access_token"])
        steps = [step("goto", "Open the app", value="/index.html")]
        _, version_id = await approved_version(client, headers, site_url, steps, with_data=False)
        started = await client.post(f"{API}/versions/{version_id}/run", headers=headers, json={})
        run = await wait_finished(client, headers, started.json()["id"])
    assert run["status"] == "failed"
    assert run["test"]["steps"][0]["error_code"] == "step.navigation_blocked"
    assert "private" in run["test"]["steps"][0]["error_message"]


async def test_cancel_stops_a_running_test(runner: Ctx, site_url: str) -> None:
    client, headers = runner
    steps = [
        step("goto", "Open the app", value="/index.html"),
        step(
            "wait_for",
            "Wait for something that never appears",
            locator=locator("text", "Never shown"),
            timeout_ms=60_000,
        ),
    ]
    _, version_id = await approved_version(client, headers, site_url, steps, with_data=False)
    started = (
        await client.post(f"{API}/versions/{version_id}/run", headers=headers, json={})
    ).json()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        run = (await client.get(f"{API}/executions/{started['id']}", headers=headers)).json()
        if run["test"]["steps"][1]["status"] == "running":
            break
        await asyncio.sleep(0.1)
    cancelled = await client.post(f"{API}/executions/{started['id']}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["cancel_requested"] is True
    began = time.monotonic()
    run = await wait_finished(client, headers, started["id"], seconds=20)
    assert time.monotonic() - began < 10
    assert run["status"] == "cancelled"
    events = (await client.get(f"{API}/executions/{run['id']}/events", headers=headers)).json()
    assert events[-1]["type"] == "execution.cancelled"
    again = await client.post(f"{API}/executions/{started['id']}/cancel", headers=headers)
    assert again.status_code == 409


async def test_run_validation_and_ownership(
    runner: Ctx, client_factory: ClientFactory, site_url: str
) -> None:
    client, headers = runner
    project, version_id = await approved_version(client, headers, site_url, LOGIN_STEPS)
    env_id = project["environments"][0]["id"]
    await client.delete(f"{API}/environments/{env_id}/variables/API_TOKEN", headers=headers)
    missing = await client.post(f"{API}/versions/{version_id}/run", headers=headers, json={})
    assert missing.status_code == 422
    assert missing.json()["error"]["details"]["missing"] == ["{{secret.API_TOKEN}}"]

    other = bearer((await register(client, email="eve@example.com")).json()["access_token"])
    assert (
        await client.post(f"{API}/versions/{version_id}/run", headers=other, json={})
    ).status_code == 404
    wrong_env = await client.post(
        f"{API}/versions/{version_id}/run",
        headers=headers,
        json={"environment_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert wrong_env.status_code == 422

    steps = [step("goto", "Open the app", value="/index.html")]
    _, ok_version = await approved_version(client, headers, site_url, steps, with_data=False)
    run = (await client.post(f"{API}/versions/{ok_version}/run", headers=headers, json={})).json()
    run = await wait_finished(client, headers, run["id"])
    artifact_id = run["artifacts"][0]["id"]
    for path in (
        f"/executions/{run['id']}",
        f"/executions/{run['id']}/events",
        f"/executions/{run['id']}/events/stream",
        f"/artifacts/{artifact_id}/content",
    ):
        assert (await client.get(f"{API}{path}", headers=other)).status_code == 404, path
    assert (await client.get(f"{API}/executions", headers=other)).json() == []

    runtime = (await client.get(f"{API}/execution-runtime", headers=headers)).json()
    assert runtime["mode"] == "inline" and runtime["isolated"] is False
    assert runtime["browsers"]["chromium"] is True and runtime["available"] is True


async def test_long_steps_stream_live_frames_and_lists_filter(runner: Ctx, site_url: str) -> None:
    client, headers = runner
    steps = [
        step("goto", "Open the app", value="/index.html"),
        step(
            "wait_for",
            "Wait for something that never appears",
            locator=locator("text", "Never shown"),
            timeout_ms=3500,
        ),
    ]
    _, version_id = await approved_version(client, headers, site_url, steps, with_data=False)
    started = await client.post(f"{API}/versions/{version_id}/run", headers=headers, json={})
    run = await wait_finished(client, headers, started.json()["id"])
    assert run["status"] == "failed"

    frames = [a for a in run["artifacts"] if a["kind"] == "frame"]
    assert len(frames) >= 2  # about one per second while the 3.5 s wait was running
    assert all(f["step_index"] == 1 and f["content_type"] == "image/jpeg" for f in frames)
    events = (await client.get(f"{API}/executions/{run['id']}/events", headers=headers)).json()
    live = [e for e in events if e["type"] == "browser.frame" and e["data"].get("interim")]
    assert len(live) == len(frames)
    # Live frames arrive while the step runs: before the step's result event.
    failed_at = next(e["seq"] for e in events if e["type"] == "browser.step.failed")
    assert all(e["seq"] < failed_at for e in live)
    body = await client.get(f"{API}/artifacts/{frames[0]['id']}/content", headers=headers)
    assert body.content[:3] == b"\xff\xd8\xff"

    failed = (await client.get(f"{API}/executions?status=failed", headers=headers)).json()
    assert [r["id"] for r in failed] == [run["id"]]
    assert (await client.get(f"{API}/executions?status=passed", headers=headers)).json() == []
    assert (await client.get(f"{API}/executions?kind=workflow", headers=headers)).json() == []
    assert len((await client.get(f"{API}/executions?kind=test_run", headers=headers)).json()) == 1
