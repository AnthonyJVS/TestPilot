"""Failure analysis and human-approved repair, end to end (real Chromium, fake AI provider)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.services.ai.types import CapabilityStatus
from tests.conftest import ClientFactory, bearer, register
from tests.fakes import FakeProvider, FakeState, fake_registry, vision_model
from tests.integration.test_execution_api import (
    approved_version,
    locator,
    site_url,
    step,
    wait_finished,
)
from tests.integration.test_testing_api import route_ai

__all__ = ["site_url"]

API = "/api/v1"
Ctx = tuple[httpx.AsyncClient, dict[str, str]]

BROKEN = [
    step("goto", "Open the app", value="/index.html"),
    step("click", "Log in", locator=locator("role", "Log in", role="button"), timeout_ms=1000),
    step(
        "expect_text", "Greeting appears", locator=locator("test_id", "greeting"), value="Signed in"
    ),
]

FIX = {
    "verdict": "fix_test",
    "rationale": "The button is now called 'Sign in'.",
    "changes": [
        {
            "op": "replace",
            "step_index": 1,
            "step": {
                "action": "click",
                "description": "Sign in",
                "locator": {"strategy": "role", "role": "button", "value": "Sign in"},
            },
            "reason": "Renamed button",
        }
    ],
}


@pytest.fixture(autouse=True)
def _reset_fake() -> None:
    FakeProvider.state = FakeState()


@pytest.fixture
async def qa(client_factory: ClientFactory, tmp_path: Path) -> AsyncIterator[Ctx]:
    async with client_factory(
        registry=fake_registry(),
        browser_allow_private_network=True,
        artifacts_dir=str(tmp_path / "artifacts"),
    ) as client:
        headers = bearer((await register(client)).json()["access_token"])
        yield client, headers


async def run_version(
    client: httpx.AsyncClient, headers: dict[str, str], version_id: str
) -> dict[str, Any]:
    started = await client.post(f"{API}/versions/{version_id}/run", headers=headers, json={})
    assert started.status_code == 202, started.text
    return await wait_finished(client, headers, started.json()["id"])


def queue(*outcomes: Any) -> None:
    FakeProvider.state.script.setdefault("fake", []).extend(outcomes)


async def test_analysis_repair_approval_and_rollback(qa: Ctx, site_url: str) -> None:
    client, headers = qa
    # A model with proven vision gets the failing step's screenshot.
    FakeProvider.state.models["fake"] = [
        vision_model("fake-pro", CapabilityStatus.SUPPORTED),
        vision_model("fake-text", CapabilityStatus.UNSUPPORTED),
    ]
    await route_ai(client, headers)
    _, version_id = await approved_version(client, headers, site_url, BROKEN, with_data=False)
    run = await run_version(client, headers, version_id)
    assert run["status"] == "failed"
    assert run["test"]["steps"][1]["status"] == "failed"

    # Analysis: verified evidence from the run, AI hypotheses that cite it.
    nothing = (
        await client.get(f"{API}/executions/{run['id']}/failure-analysis", headers=headers)
    ).json()
    assert nothing == {"analysis": None, "proposals": []}
    created = await client.post(f"{API}/executions/{run['id']}/failure-analysis", headers=headers)
    assert created.status_code == 201, created.text
    analysis = created.json()
    kinds = [e["kind"] for e in analysis["evidence"]]
    assert kinds[:4] == ["step", "error", "page", "snapshot"]
    assert [e["id"] for e in analysis["evidence"]][:2] == ["E1", "E2"]
    snapshot = next(e for e in analysis["evidence"] if e["kind"] == "snapshot")
    assert 'button "Sign in"' in snapshot["detail"]
    history = next(e for e in analysis["evidence"] if e["kind"] == "history")
    assert history["detail"] == "This is the first run."
    assert analysis["result"]["category"] == "locator_changed"
    # Citations of evidence that does not exist are dropped.
    assert analysis["result"]["hypotheses"][0]["evidence_ids"] == ["E1", "E4"]
    assert analysis["used_screenshot"] is True
    call = FakeProvider.state.calls[-1].request
    assert call.schema_name == "FailureAnalysisOutput"
    assert call.images and call.images[0].mime_type == "image/jpeg"
    assert "<untrusted>" in call.prompt and 'button \\"Sign in\\"' not in call.prompt
    assert 'button "Sign in"' in call.prompt

    # Repair: a minimal, validated edit shown as a diff; nothing changes yet.
    queue(FIX)
    proposed = await client.post(f"{API}/failure-analyses/{analysis['id']}/repair", headers=headers)
    assert proposed.status_code == 201, proposed.text
    proposal = proposed.json()
    assert proposal["status"] == "proposed"
    assert [row["kind"] for row in proposal["diff"]] == ["same", "changed", "same"]
    assert proposal["diff"][1]["before"]["locator"]["value"] == "Log in"
    assert proposal["diff"][1]["after"]["locator"]["value"] == "Sign in"
    case_id = proposal["test_case_id"]
    case = (await client.get(f"{API}/cases/{case_id}", headers=headers)).json()
    assert case["current_version_id"] == version_id

    # Approval creates version 2 through the normal approval path; the fixed test passes.
    approved = await client.post(
        f"{API}/repair-proposals/{proposal['id']}/approve", headers=headers
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["version"] == 2
    assert approved.json()["proposal"]["status"] == "approved"
    case = (await client.get(f"{API}/cases/{case_id}", headers=headers)).json()
    assert case["current_version_id"] == approved.json()["version_id"]
    assert case["latest_plan"]["source"] == "repair"
    rerun = await run_version(client, headers, approved.json()["version_id"])
    assert rerun["status"] == "passed", rerun
    again = await client.post(f"{API}/repair-proposals/{proposal['id']}/approve", headers=headers)
    assert again.status_code == 409

    # Rollback makes version 1 current again; versions themselves never change.
    rolled = await client.post(f"{API}/versions/{version_id}/rollback", headers=headers)
    assert rolled.status_code == 200 and rolled.json()["version"] == 1
    case = (await client.get(f"{API}/cases/{case_id}", headers=headers)).json()
    assert case["current_version_id"] == version_id and len(case["versions"]) == 2
    same = await client.post(f"{API}/versions/{version_id}/rollback", headers=headers)
    assert same.status_code == 409

    review = (
        await client.get(f"{API}/executions/{run['id']}/failure-analysis", headers=headers)
    ).json()
    assert review["analysis"]["id"] == analysis["id"]
    assert [p["status"] for p in review["proposals"]] == ["approved"]


async def test_reject_invalid_no_change_stale_and_ownership(qa: Ctx, site_url: str) -> None:
    client, headers = qa
    await route_ai(client, headers)
    _, version_id = await approved_version(client, headers, site_url, BROKEN, with_data=False)
    run = await run_version(client, headers, version_id)
    analysis = (
        await client.post(f"{API}/executions/{run['id']}/failure-analysis", headers=headers)
    ).json()
    assert analysis["used_screenshot"] is False  # vision not proven for this model
    assert not FakeProvider.state.calls[-1].request.images

    # The application is at fault: no test change is proposed.
    no_change = (
        await client.post(f"{API}/failure-analyses/{analysis['id']}/repair", headers=headers)
    ).json()
    assert no_change["status"] == "no_change" and no_change["diff"] == []
    assert (
        await client.post(f"{API}/repair-proposals/{no_change['id']}/approve", headers=headers)
    ).status_code == 409

    # An edit pointing outside the plan is reported as invalid and cannot be approved.
    queue({**FIX, "changes": [{**FIX["changes"][0], "step_index": 9}]})
    invalid = (
        await client.post(f"{API}/failure-analyses/{analysis['id']}/repair", headers=headers)
    ).json()
    assert invalid["status"] == "invalid"
    assert invalid["issues"][0]["code"] == "repair.not_applicable"
    assert (
        await client.post(f"{API}/repair-proposals/{invalid['id']}/approve", headers=headers)
    ).status_code == 409

    # Rejection is recorded; a newer proposal supersedes an open one.
    queue(FIX, FIX)
    first = (
        await client.post(f"{API}/failure-analyses/{analysis['id']}/repair", headers=headers)
    ).json()
    second = (
        await client.post(f"{API}/failure-analyses/{analysis['id']}/repair", headers=headers)
    ).json()
    review = (
        await client.get(f"{API}/executions/{run['id']}/failure-analysis", headers=headers)
    ).json()
    statuses = {p["id"]: p["status"] for p in review["proposals"]}
    assert statuses[first["id"]] == "superseded" and statuses[second["id"]] == "proposed"
    rejected = await client.post(
        f"{API}/repair-proposals/{second['id']}/reject",
        headers=headers,
        json={"note": "Wrong button"},
    )
    assert (
        rejected.json()["status"] == "rejected"
        and rejected.json()["decision_note"] == "Wrong button"
    )

    other = bearer((await register(client, email="eve@example.com")).json()["access_token"])
    for method, path in (
        ("GET", f"/executions/{run['id']}/failure-analysis"),
        ("POST", f"/executions/{run['id']}/failure-analysis"),
        ("POST", f"/failure-analyses/{analysis['id']}/repair"),
        ("POST", f"/repair-proposals/{second['id']}/approve"),
        ("POST", f"/versions/{version_id}/rollback"),
    ):
        response = await client.request(method, f"{API}{path}", headers=other)
        assert response.status_code == 404, path

    ok_steps = [step("goto", "Open the app", value="/index.html")]
    _, ok_version = await approved_version(client, headers, site_url, ok_steps, with_data=False)
    passed = await run_version(client, headers, ok_version)
    refused = await client.post(
        f"{API}/executions/{passed['id']}/failure-analysis", headers=headers
    )
    assert refused.status_code == 409


async def test_failure_analyzer_node_explains_a_failed_node(qa: Ctx, site_url: str) -> None:
    client, headers = qa
    await route_ai(client, headers)
    project = (
        await client.post(
            f"{API}/projects", headers=headers, json={"name": "Flow", "base_url": site_url}
        )
    ).json()
    workflow = (
        await client.post(
            f"{API}/projects/{project['id']}/workflows", headers=headers, json={"name": "Diagnose"}
        )
    ).json()
    graph = {
        "nodes": [
            {"id": "launch", "type": "browser.launch", "config": {}},
            {"id": "open", "type": "browser.navigate", "config": {"url": "/index.html"}},
            {
                "id": "click",
                "type": "browser.click",
                "label": "Click Log in",
                "config": {
                    "locator": {"strategy": "role", "role": "button", "value": "Log in"},
                    "timeout_ms": 1000,
                },
            },
            {"id": "why", "type": "ai.failure_analyzer", "config": {}},
            {"id": "out", "type": "data.output", "config": {}},
        ],
        "edges": [
            {
                "id": "e1",
                "source": "launch",
                "source_handle": "session",
                "target": "open",
                "target_handle": "session",
            },
            {
                "id": "e2",
                "source": "open",
                "source_handle": "session",
                "target": "click",
                "target_handle": "session",
            },
            {
                "id": "e3",
                "source": "click",
                "source_handle": "error",
                "target": "why",
                "target_handle": "failure",
            },
            {
                "id": "e4",
                "source": "why",
                "source_handle": "analysis",
                "target": "out",
                "target_handle": "value",
            },
        ],
    }
    saved = await client.post(
        f"{API}/workflows/{workflow['id']}/versions", headers=headers, json={"graph": graph}
    )
    assert [i for i in saved.json()["latest"]["issues"] if i["severity"] == "error"] == []
    started = (
        await client.post(f"{API}/workflows/{workflow['id']}/run", headers=headers, json={})
    ).json()
    execution = await wait_finished(client, headers, started["id"])
    assert execution["status"] == "passed", execution
    nodes = {n["node_id"]: n for n in execution["workflow"]["nodes"]}
    assert nodes["click"]["status"] == "failed"
    analysis = nodes["out"]["output"]["value"]
    assert analysis["category"] == "locator_changed"
    assert any(e["kind"] == "snapshot" and "Sign in" in e["detail"] for e in analysis["evidence"])
    assert analysis["evidence"][0]["title"] == "Node 'Click Log in' failed"
    events = (
        await client.get(f"{API}/executions/{execution['id']}/events", headers=headers)
    ).json()
    ai = [e for e in events if e["type"] == "ai.request.completed"]
    assert ai and ai[0]["node_id"] == "why" and ai[0]["data"]["task"] == "failure_analysis"
