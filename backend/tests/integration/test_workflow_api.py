"""Workflow Studio API and DAG engine end to end (real Chromium against a local fixture site)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.conftest import ClientFactory, bearer, register
from tests.fakes import FakeProvider, FakeState, fake_registry
from tests.integration.test_execution_api import (
    LOGIN_STEPS,
    SECRET,
    approved_version,
    site_url,
    wait_finished,
)
from tests.integration.test_testing_api import route_ai

__all__ = ["site_url"]  # module-scoped fixture re-used from the execution tests

API = "/api/v1"
Ctx = tuple[httpx.AsyncClient, dict[str, str]]


@pytest.fixture(autouse=True)
def _reset_fake() -> None:
    FakeProvider.state = FakeState()


@pytest.fixture
async def studio(client_factory: ClientFactory, tmp_path: Path) -> AsyncIterator[Ctx]:
    async with client_factory(
        registry=fake_registry(),
        browser_allow_private_network=True,
        artifacts_dir=str(tmp_path / "artifacts"),
    ) as client:
        token = (await register(client)).json()["access_token"]
        yield client, bearer(token)


def node(node_id: str, type_: str, label: str = "", **config: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "label": label, "config": config}


def edge(source: str, source_handle: str, target: str, target_handle: str) -> dict[str, Any]:
    return {
        "id": f"{source}-{target}-{target_handle}"[:40],
        "source": source,
        "source_handle": source_handle,
        "target": target,
        "target_handle": target_handle,
    }


async def project_with_data(
    client: httpx.AsyncClient, headers: dict[str, str], base_url: str
) -> dict[str, Any]:
    project = (
        await client.post(
            f"{API}/projects",
            headers=headers,
            json={"name": f"Site {uuid.uuid4().hex[:6]}", "base_url": base_url},
        )
    ).json()
    env_id = project["environments"][0]["id"]
    for name, value, secret in (
        ("LOGIN_EMAIL", "ada@example.com", False),
        ("API_TOKEN", SECRET, True),
    ):
        await client.put(
            f"{API}/environments/{env_id}/variables/{name}",
            headers=headers,
            json={"value": value, "is_secret": secret},
        )
    return project


async def workflow_with(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    project: dict[str, Any],
    graph: dict[str, Any],
) -> dict[str, Any]:
    created = await client.post(
        f"{API}/projects/{project['id']}/workflows",
        headers=headers,
        json={"name": f"Flow {uuid.uuid4().hex[:6]}"},
    )
    assert created.status_code == 201, created.text
    saved = await client.post(
        f"{API}/workflows/{created.json()['id']}/versions", headers=headers, json={"graph": graph}
    )
    assert saved.status_code == 201, saved.text
    workflow: dict[str, Any] = saved.json()
    return workflow


async def run(
    client: httpx.AsyncClient, headers: dict[str, str], workflow_id: str
) -> dict[str, Any]:
    started = await client.post(f"{API}/workflows/{workflow_id}/run", headers=headers, json={})
    assert started.status_code == 202, started.text
    assert started.json()["kind"] == "workflow"
    return await wait_finished(client, headers, started.json()["id"])


def nodes_by_id(execution: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {n["node_id"]: n for n in execution["workflow"]["nodes"]}


LOCATE = {
    "email": {"strategy": "label", "value": "Email"},
    "token": {"strategy": "label", "value": "API token"},
    "sign_in": {"strategy": "role", "role": "button", "value": "Sign in"},
    "greeting": {"strategy": "test_id", "value": "greeting"},
}


async def test_node_types_describe_ports_schemas_and_planned_nodes(studio: Ctx) -> None:
    client, headers = studio
    types = {
        t["type"]: t
        for t in (await client.get(f"{API}/workflow-node-types", headers=headers)).json()
    }
    assert types["browser.fill"]["available"] is True
    assert {p["name"] for p in types["browser.fill"]["outputs"]} == {"session", "error"}
    assert types["browser.fill"]["config_schema"]["properties"]["value"]["type"] == "string"
    assert types["logic.condition"]["outputs"][0]["name"] == "true"
    assert types["data.input"]["entry"] is True
    assert types["ai.visual_analyzer"]["available"] is False
    assert types["ai.visual_analyzer"]["milestone"] is None


async def test_validation_reports_graph_problems_and_blocks_runs(
    studio: Ctx, site_url: str
) -> None:
    client, headers = studio
    project = await project_with_data(client, headers, site_url)
    graph = {
        "nodes": [
            node("in", "data.input", text="hi"),
            node("nav", "browser.navigate", url="https://evil.example.org/"),
            node("click", "browser.click"),
            node("plan", "ai.visual_analyzer"),
            node("odd", "does.not.exist"),
            node("bad", "browser.assert", check="text", expected=""),
        ],
        "edges": [edge("in", "text", "click", "session")],
    }
    workflow = await workflow_with(client, headers, project, graph)
    codes = {
        (i["code"], i.get("node_id") or i.get("edge_id")) for i in workflow["latest"]["issues"]
    }
    assert ("edge.incompatible", "in-click-session") in codes
    assert ("node.input_missing", "nav") in codes
    assert ("node.domain_not_allowed", "nav") in codes
    assert ("node.unavailable", "plan") in codes
    assert ("node.unknown_type", "odd") in codes
    assert ("node.invalid_config", "bad") in codes

    rejected = await client.post(f"{API}/workflows/{workflow['id']}/run", headers=headers, json={})
    assert rejected.status_code == 422
    assert rejected.json()["error"]["details"]["issues"]

    cyclic = {
        "nodes": [node("a", "logic.delay", seconds=0), node("b", "logic.delay", seconds=0)],
        "edges": [edge("a", "value", "b", "value"), edge("b", "value", "a", "value")],
    }
    check = await client.post(
        f"{API}/workflows/{workflow['id']}/validate", headers=headers, json={"graph": cyclic}
    )
    assert check.json()["runnable"] is False
    assert any(i["code"] == "graph.cycle" for i in check.json()["issues"])


async def test_versions_duplicate_and_ownership(studio: Ctx, site_url: str) -> None:
    client, headers = studio
    project = await project_with_data(client, headers, site_url)
    graph = {"nodes": [node("wait", "logic.delay", seconds=0)], "edges": []}
    workflow = await workflow_with(client, headers, project, graph)
    assert workflow["latest"]["version"] == 2  # v1 is the blank template
    same = await client.post(
        f"{API}/workflows/{workflow['id']}/versions", headers=headers, json={"graph": graph}
    )
    assert same.json()["latest"]["version"] == 2  # unchanged graphs do not create versions
    copy = await client.post(f"{API}/workflows/{workflow['id']}/duplicate", headers=headers)
    assert copy.status_code == 201 and copy.json()["name"].endswith("(copy)")
    assert copy.json()["latest"]["graph"]["nodes"][0]["id"] == "wait"
    listed = (
        await client.get(f"{API}/workflows?project_id={project['id']}", headers=headers)
    ).json()
    assert len(listed) == 2

    other = bearer((await register(client, email="eve@example.com")).json()["access_token"])
    for method, path in (
        ("GET", f"/workflows/{workflow['id']}"),
        ("POST", f"/workflows/{workflow['id']}/run"),
        ("POST", f"/workflows/{workflow['id']}/duplicate"),
        ("DELETE", f"/workflows/{workflow['id']}"),
    ):
        response = await client.request(
            method, f"{API}{path}", headers=other, json={} if method == "POST" else None
        )
        assert response.status_code == 404, path
    assert (await client.get(f"{API}/workflows", headers=other)).json() == []


async def test_browser_workflow_runs_with_branches_and_evidence(studio: Ctx, site_url: str) -> None:
    client, headers = studio
    project = await project_with_data(client, headers, site_url)
    graph = {
        "nodes": [
            node("launch", "browser.launch", "Launch"),
            node("open", "browser.navigate", "Open app", url="/index.html"),
            node(
                "email",
                "browser.fill",
                "Type email",
                locator=LOCATE["email"],
                value="{{env.LOGIN_EMAIL}}",
            ),
            node(
                "token",
                "browser.fill",
                "Type token",
                locator=LOCATE["token"],
                value="{{secret.API_TOKEN}}",
            ),
            node("sign_in", "browser.click", "Sign in", locator=LOCATE["sign_in"]),
            node(
                "check",
                "browser.assert",
                "Greeting",
                check="text",
                locator=LOCATE["greeting"],
                expected="ada@example.com",
            ),
            node("console", "browser.inspect_console", "Console"),
            node(
                "errors",
                "logic.condition",
                "Any errors?",
                path="errors",
                operator="greater_than",
                value="0",
            ),
            node("noisy", "data.output", "Page logged errors"),
            node("clean", "data.output", "Clean page"),
        ],
        "edges": [
            edge("launch", "session", "open", "session"),
            edge("open", "session", "email", "session"),
            edge("email", "session", "token", "session"),
            edge("token", "session", "sign_in", "session"),
            edge("sign_in", "session", "check", "session"),
            edge("check", "session", "console", "session"),
            edge("console", "report", "errors", "value"),
            edge("errors", "true", "noisy", "value"),
            edge("errors", "false", "clean", "value"),
        ],
    }
    workflow = await workflow_with(client, headers, project, graph)
    assert [i for i in workflow["latest"]["issues"] if i["severity"] == "error"] == []
    execution = await run(client, headers, workflow["id"])

    assert execution["status"] == "passed", execution
    nodes = nodes_by_id(execution)
    assert nodes["errors"]["summary"] == "errors greater_than → true"
    assert nodes["noisy"]["status"] == "completed"
    assert nodes["noisy"]["output"]["value"]["errors"] >= 1  # console.error, 404, blocked probe
    assert nodes["clean"]["status"] == "skipped"
    assert all(n["status"] == "completed" for k, n in nodes.items() if k != "clean")
    assert execution["workflow"]["graph"]["nodes"][0]["id"] == "launch"
    # Secrets: trace off, never stored or streamed.
    assert any("secret" in note for note in execution["notes"])
    events = (
        await client.get(f"{API}/executions/{execution['id']}/events", headers=headers)
    ).json()
    assert SECRET not in str(events) and SECRET not in str(execution)
    frames = [e for e in events if e["type"] == "browser.frame"]
    assert {f["node_id"] for f in frames} >= {"open", "email", "token", "sign_in", "check"}
    shots = [a for a in execution["artifacts"] if a["kind"] == "screenshot"]
    assert shots and all(a["node_id"] for a in shots)
    assert "trace" not in {a["kind"] for a in execution["artifacts"]}
    started = [e["node_id"] for e in events if e["type"] == "node.started"]
    assert started[:2] == ["launch", "open"]
    assert events[-1]["type"] == "execution.completed"

    history = (
        await client.get(f"{API}/executions?workflow_id={workflow['id']}", headers=headers)
    ).json()
    assert history[0]["kind"] == "workflow" and history[0]["steps_passed"] == 9
    assert history[0]["steps_total"] == 10


async def test_retries_error_branch_and_unhandled_failure(studio: Ctx, site_url: str) -> None:
    client, headers = studio
    project = await project_with_data(client, headers, site_url)
    failing = node(
        "title",
        "browser.assert",
        "Title check",
        check="title",
        expected="Wrong title",
        timeout_ms=300,
    )
    failing["retry"] = {"max_attempts": 2, "retry_on": "any", "base_seconds": 0}
    base_nodes = [
        node("launch", "browser.launch"),
        node("open", "browser.navigate", url="/index.html"),
        failing,
        node("after", "data.output", "After"),
    ]
    base_edges = [
        edge("launch", "session", "open", "session"),
        edge("open", "session", "title", "session"),
        edge("title", "session", "after", "value"),
    ]
    handled = await workflow_with(
        client,
        headers,
        project,
        {
            "nodes": [*base_nodes, node("report", "data.output", "Failure report")],
            "edges": [*base_edges, edge("title", "error", "report", "value")],
        },
    )
    execution = await run(client, headers, handled["id"])
    nodes = nodes_by_id(execution)
    assert execution["status"] == "passed"
    assert nodes["title"]["status"] == "failed" and nodes["title"]["attempts"] == 2
    assert nodes["after"]["status"] == "skipped"
    assert nodes["report"]["output"]["value"]["code"] == "step.assertion_failed"
    events = (
        await client.get(f"{API}/executions/{execution['id']}/events", headers=headers)
    ).json()
    assert [e["type"] for e in events].count("node.retry_scheduled") == 1

    unhandled = await workflow_with(
        client, headers, project, {"nodes": base_nodes, "edges": base_edges}
    )
    execution = await run(client, headers, unhandled["id"])
    nodes = nodes_by_id(execution)
    assert execution["status"] == "failed"
    assert execution["error_code"] == "step.assertion_failed"
    assert "Wrong title" in execution["error_message"]
    assert nodes["after"]["status"] == "skipped"


async def test_run_test_template_runs_an_approved_test(studio: Ctx, site_url: str) -> None:
    client, headers = studio
    project, _ = await approved_version(client, headers, site_url, LOGIN_STEPS)
    cases = (await client.get(f"{API}/projects/{project['id']}/cases", headers=headers)).json()
    created = await client.post(
        f"{API}/projects/{project['id']}/workflows",
        headers=headers,
        json={"name": "Nightly", "template": "run_test", "test_case_id": cases[0]["id"]},
    )
    assert created.status_code == 201
    assert [i for i in created.json()["latest"]["issues"] if i["severity"] == "error"] == []
    execution = await run(client, headers, created.json()["id"])
    nodes = nodes_by_id(execution)
    assert execution["status"] == "passed", execution
    assert nodes["test"]["output"]["result"]["steps_passed"] == len(LOGIN_STEPS)
    assert nodes["result"]["status"] == "completed" and nodes["failure"]["status"] == "skipped"


async def test_ai_nodes_analyze_and_plan_through_the_router(studio: Ctx, site_url: str) -> None:
    client, headers = studio
    await route_ai(client, headers)
    project = await project_with_data(client, headers, site_url)
    graph = {
        "nodes": [
            node(
                "scenario",
                "data.input",
                text="Sign in with the test account and see the dashboard.",
            ),
            node("analyze", "ai.requirement_analyzer"),
            node("plan", "ai.test_planner"),
            node("out", "data.output", "Plan"),
        ],
        "edges": [
            edge("scenario", "text", "analyze", "scenario"),
            edge("scenario", "text", "plan", "scenario"),
            edge("analyze", "analysis", "plan", "analysis"),
            edge("plan", "plan", "out", "value"),
        ],
    }
    workflow = await workflow_with(client, headers, project, graph)
    execution = await run(client, headers, workflow["id"])
    assert execution["status"] == "passed", execution
    plan = nodes_by_id(execution)["out"]["output"]["value"]
    assert plan["steps"] and plan["name"]
    events = (
        await client.get(f"{API}/executions/{execution['id']}/events", headers=headers)
    ).json()
    ai = [e for e in events if e["type"] == "ai.request.completed"]
    assert [e["data"]["task"] for e in ai] == ["requirement_analysis", "test_planning"]
    assert ai[0]["data"]["actual_model"].startswith("fake-pro")  # as reported by the provider

    detail = await client.get(
        f"{API}/ai/requests/{ai[1]['data']['ai_request_id']}", headers=headers
    )
    assert detail.status_code == 200
    assert detail.json()["task"] == "test_planning" and detail.json()["origin"] == "workflow"
    other = bearer((await register(client, email="mallory@example.com")).json()["access_token"])
    hidden = await client.get(f"{API}/ai/requests/{ai[1]['data']['ai_request_id']}", headers=other)
    assert hidden.status_code == 404


async def test_cancel_stops_running_nodes(studio: Ctx, site_url: str) -> None:
    client, headers = studio
    project = await project_with_data(client, headers, site_url)
    workflow = await workflow_with(
        client,
        headers,
        project,
        {
            "nodes": [node("wait", "logic.delay", seconds=60), node("out", "data.output")],
            "edges": [edge("wait", "value", "out", "value")],
        },
    )
    started = (
        await client.post(f"{API}/workflows/{workflow['id']}/run", headers=headers, json={})
    ).json()
    import asyncio

    for _ in range(50):
        current = (await client.get(f"{API}/executions/{started['id']}", headers=headers)).json()
        if nodes_by_id(current)["wait"]["status"] == "running":
            break
        await asyncio.sleep(0.1)
    await client.post(f"{API}/executions/{started['id']}/cancel", headers=headers)
    execution = await wait_finished(client, headers, started["id"], seconds=15)
    nodes = nodes_by_id(execution)
    assert execution["status"] == "cancelled"
    assert nodes["wait"]["status"] == "cancelled"
    assert nodes["out"]["status"] == "cancelled"
