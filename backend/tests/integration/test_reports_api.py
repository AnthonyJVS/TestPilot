"""Self-contained HTML run reports."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from tests.conftest import ClientFactory, bearer, register
from tests.fakes import FakeProvider, FakeState, fake_registry
from tests.integration.test_execution_api import site_url, wait_finished
from tests.integration.test_testing_api import route_ai

__all__ = ["site_url"]

API = "/api/v1"
Ctx = tuple[httpx.AsyncClient, dict[str, str]]
EVIL = 'Checkout <script>alert("x")</script> & "quotes"'


@pytest.fixture(autouse=True)
def _reset_fake() -> None:
    FakeProvider.state = FakeState()


@pytest.fixture
async def ctx(client_factory: ClientFactory, tmp_path: Path) -> AsyncIterator[Ctx]:
    async with client_factory(
        registry=fake_registry(),
        browser_allow_private_network=True,
        artifacts_dir=str(tmp_path / "artifacts"),
    ) as client:
        yield client, bearer((await register(client)).json()["access_token"])


async def failing_run(client: httpx.AsyncClient, headers: dict[str, str], base_url: str) -> dict:
    project = (
        await client.post(
            f"{API}/projects", headers=headers, json={"name": "Shop", "base_url": base_url}
        )
    ).json()
    suites = (await client.get(f"{API}/projects/{project['id']}/suites", headers=headers)).json()
    case = (
        await client.post(
            f"{API}/projects/{project['id']}/cases",
            headers=headers,
            json={"suite_id": suites[0]["id"], "name": EVIL},
        )
    ).json()
    plan = {
        "name": "Report",
        "steps": [
            {"action": "goto", "description": "Open <b>the</b> app", "value": "/index.html"},
            {
                "action": "click",
                "description": "Log in",
                "locator": {"strategy": "role", "role": "button", "value": "Log in"},
                "timeout_ms": 800,
            },
        ],
    }
    draft = (
        await client.post(f"{API}/cases/{case['id']}/plans", headers=headers, json={"plan": plan})
    ).json()
    version = (
        await client.post(f"{API}/plans/{draft['latest_plan']['id']}/approve", headers=headers)
    ).json()
    started = (
        await client.post(f"{API}/versions/{version['id']}/run", headers=headers, json={})
    ).json()
    return await wait_finished(client, headers, started["id"])


async def test_test_run_report_is_self_contained_and_escaped(ctx: Ctx, site_url: str) -> None:
    client, headers = ctx
    await route_ai(client, headers)
    run = await failing_run(client, headers, site_url)
    assert run["status"] == "failed"
    await client.post(f"{API}/executions/{run['id']}/failure-analysis", headers=headers)

    response = await client.get(f"{API}/executions/{run['id']}/report", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["content-disposition"].startswith('attachment; filename="testpilot-')
    html = response.text
    assert "default-src 'none'; img-src data:; style-src 'unsafe-inline'" in html
    # Untrusted text is escaped: no live markup from test names or step descriptions.
    assert "<script>" not in html and "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in html
    assert "<b>the</b>" not in html and "Open &lt;b&gt;the&lt;/b&gt; app" in html
    assert '<span class="badge failed">failed</span>' in html
    assert "data:image/jpeg;base64," in html  # screenshots embedded
    assert "Verified evidence" in html and "hypotheses, not facts" in html
    assert "AI used in this run" in html and "fake/fake-pro" in html
    assert "Console and network" in html

    usage = (await client.get(f"{API}/ai/usage?days=7", headers=headers)).json()
    assert len(usage["days"]) == 7 and usage["days"][-1]["requests"] == 1
    assert usage["totals"]["requests"] == 1 and usage["totals"]["failed"] == 0
    assert usage["models"][0]["model"].startswith("fake-pro")
    assert usage["tasks"][0]["task"] == "failure_analysis"
    assert usage["origins"] == {"failure_analysis": 1} and usage["requests_today"] == 1
    assert (await client.get(f"{API}/ai/usage?days=0", headers=headers)).status_code == 422

    other = bearer((await register(client, email="eve@example.com")).json()["access_token"])
    assert (
        await client.get(f"{API}/executions/{run['id']}/report", headers=other)
    ).status_code == 404


async def test_workflow_report_lists_nodes(ctx: Ctx, site_url: str) -> None:
    client, headers = ctx
    project = (
        await client.post(
            f"{API}/projects", headers=headers, json={"name": "Flow", "base_url": site_url}
        )
    ).json()
    workflow = (
        await client.post(
            f"{API}/projects/{project['id']}/workflows", headers=headers, json={"name": "Nightly"}
        )
    ).json()
    graph = {
        "nodes": [
            {"id": "launch", "type": "browser.launch", "label": "Launch", "config": {}},
            {
                "id": "open",
                "type": "browser.navigate",
                "label": "Open",
                "config": {"url": "/index.html"},
            },
        ],
        "edges": [
            {
                "id": "e1",
                "source": "launch",
                "source_handle": "session",
                "target": "open",
                "target_handle": "session",
            }
        ],
    }
    await client.post(
        f"{API}/workflows/{workflow['id']}/versions", headers=headers, json={"graph": graph}
    )
    started = (
        await client.post(f"{API}/workflows/{workflow['id']}/run", headers=headers, json={})
    ).json()
    run = await wait_finished(client, headers, started["id"])
    html = (await client.get(f"{API}/executions/{run['id']}/report", headers=headers)).text
    assert "Workflow run" in html and "<h2>Nodes</h2>" in html
    assert "browser.navigate" in html and '<span class="badge passed">passed</span>' in html
