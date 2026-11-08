"""Testing Workspace: projects, test data, suites, tests, AI plan generation, editing and approval."""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.infrastructure.database.models import EnvironmentVariable
from app.infrastructure.database.session import create_engine, create_session_factory
from tests.conftest import ClientFactory, bearer, register
from tests.fakes import CHECK_ANSWERS, FakeProvider, FakeState, fake_registry

API = "/api/v1"
Client = tuple[httpx.AsyncClient, dict[str, str]]


@pytest.fixture(autouse=True)
def _reset_fake() -> None:
    FakeProvider.state = FakeState()


@pytest.fixture
async def ws(client_factory: ClientFactory) -> AsyncIterator[Client]:
    async with client_factory(registry=fake_registry()) as client:
        token = (await register(client)).json()["access_token"]
        yield client, bearer(token)


async def make_project(
    client: httpx.AsyncClient, headers: dict[str, str], name: str = "Shop"
) -> dict[str, Any]:
    response = await client.post(
        f"{API}/projects",
        headers=headers,
        json={
            "name": name,
            "base_url": "https://shop.example.com/",
            "allowed_domains": ["*.cdn.example.com"],
        },
    )
    assert response.status_code == 201, response.text
    project: dict[str, Any] = response.json()
    return project


async def make_case(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    project: dict[str, Any],
    scenario: str = "Sign in and see the dashboard.",
) -> dict[str, Any]:
    suites = (await client.get(f"{API}/projects/{project['id']}/suites", headers=headers)).json()
    response = await client.post(
        f"{API}/projects/{project['id']}/cases",
        headers=headers,
        json={"suite_id": suites[0]["id"], "name": "Login works", "scenario": scenario},
    )
    assert response.status_code == 201, response.text
    case: dict[str, Any] = response.json()
    return case


async def route_ai(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    created = await client.post(
        f"{API}/ai/providers",
        headers=headers,
        json={"provider_type": "fake", "name": "Fake", "api_key": "k" * 16},
    )
    provider = (
        await client.post(f"{API}/ai/providers/{created.json()['id']}/test", headers=headers)
    ).json()["provider"]
    model = next(m["id"] for m in provider["models"] if m["model_id"] == "fake-pro")
    await client.put(
        f"{API}/ai/routing", headers=headers, json={"mode": "simple", "default_model_id": model}
    )


def plan_body(**overrides: Any) -> dict[str, Any]:
    plan = copy.deepcopy(CHECK_ANSWERS["TestPlan"])
    plan.update(overrides)
    return {"plan": plan}


# ------------------------------------------------------------------- projects


async def test_project_defaults_and_validation(ws: Client) -> None:
    client, headers = ws
    project = await make_project(client, headers)
    assert project["base_url"] == "https://shop.example.com"
    assert project["allowed_domains"] == ["shop.example.com", "*.cdn.example.com"]
    assert [e["name"] for e in project["environments"]] == ["default"]
    assert project["environments"][0]["effective_base_url"] == "https://shop.example.com"
    suites = (await client.get(f"{API}/projects/{project['id']}/suites", headers=headers)).json()
    assert [s["name"] for s in suites] == ["General"]

    bad_url = await client.post(
        f"{API}/projects", headers=headers, json={"name": "X", "base_url": "shop.example.com"}
    )
    assert bad_url.status_code == 422
    with_creds = await client.post(
        f"{API}/projects",
        headers=headers,
        json={"name": "Y", "base_url": "https://u:p@shop.example.com"},
    )
    assert with_creds.status_code == 422
    bad_domain = await client.post(
        f"{API}/projects",
        headers=headers,
        json={"name": "Z", "base_url": "https://a.example", "allowed_domains": ["not a domain"]},
    )
    assert bad_domain.status_code == 422
    duplicate = await client.post(
        f"{API}/projects", headers=headers, json={"name": "Shop", "base_url": "https://b.example"}
    )
    assert duplicate.status_code == 409


async def test_secret_variables_are_write_only_and_encrypted(ws: Client, database_url: str) -> None:
    client, headers = ws
    project = await make_project(client, headers)
    env_id = project["environments"][0]["id"]
    await client.put(
        f"{API}/environments/{env_id}/variables/LOGIN_EMAIL",
        headers=headers,
        json={"value": "qa@example.com", "is_secret": False},
    )
    updated = await client.put(
        f"{API}/environments/{env_id}/variables/LOGIN_PASSWORD",
        headers=headers,
        json={"value": "s3cr3t-Passw0rd", "is_secret": True},
    )
    assert updated.status_code == 200
    assert "s3cr3t-Passw0rd" not in updated.text
    variables = {v["name"]: v for v in updated.json()["environments"][0]["variables"]}
    assert variables["LOGIN_EMAIL"]["value"] == "qa@example.com"
    assert variables["LOGIN_PASSWORD"] == {
        **variables["LOGIN_PASSWORD"],
        "value": None,
        "has_value": True,
        "is_secret": True,
    }

    engine = create_engine(database_url)
    async with create_session_factory(engine)() as session:
        stored = (
            await session.execute(
                select(EnvironmentVariable).where(EnvironmentVariable.name == "LOGIN_PASSWORD")
            )
        ).scalar_one()
        assert stored.value is None and stored.ciphertext and b"s3cr3t" not in stored.ciphertext
    await engine.dispose()

    audit = (await client.get(f"{API}/audit-logs", headers=headers)).text
    assert "project.secret.set" in audit and "s3cr3t" not in audit

    bad_name = await client.put(
        f"{API}/environments/{env_id}/variables/login-email",
        headers=headers,
        json={"value": "x", "is_secret": False},
    )
    assert bad_name.status_code == 422
    assert (await client.delete(f"{API}/environments/{env_id}", headers=headers)).status_code == 409


async def test_other_users_cannot_reach_my_workspace(client_factory: ClientFactory) -> None:
    async with client_factory(registry=fake_registry()) as client:
        alice = bearer((await register(client)).json()["access_token"])
        project = await make_project(client, alice)
        case = await make_case(client, alice, project)
        plan = (
            await client.post(f"{API}/cases/{case['id']}/plans", headers=alice, json=plan_body())
        ).json()["latest_plan"]
        version = (await client.post(f"{API}/plans/{plan['id']}/approve", headers=alice)).json()
        client.cookies.clear()
        bob = bearer(
            (await register(client, email="bob@example.com", display_name="Bob")).json()[
                "access_token"
            ]
        )

        env_id = project["environments"][0]["id"]
        for method, url in [
            ("GET", f"/projects/{project['id']}"),
            ("GET", f"/projects/{project['id']}/suites"),
            ("GET", f"/cases/{case['id']}"),
            ("GET", f"/versions/{version['id']}"),
            ("POST", f"/plans/{plan['id']}/approve"),
            ("DELETE", f"/projects/{project['id']}"),
        ]:
            response = await client.request(method, f"{API}{url}", headers=bob)
            assert response.status_code == 404, (method, url, response.status_code)
        sneaky = await client.put(
            f"{API}/environments/{env_id}/variables/X",
            headers=bob,
            json={"value": "1", "is_secret": False},
        )
        assert sneaky.status_code == 404
        mine = await make_project(client, bob, name="Bob's")
        foreign_suite = await client.post(
            f"{API}/projects/{mine['id']}/cases",
            headers=bob,
            json={"suite_id": case["suite_id"], "name": "x"},
        )
        assert foreign_suite.status_code == 404
        assert [p["name"] for p in (await client.get(f"{API}/projects", headers=bob)).json()] == [
            "Bob's"
        ]


# ---------------------------------------------------------------------- cases


async def test_case_search_filter_and_move(ws: Client) -> None:
    client, headers = ws
    project = await make_project(client, headers)
    case = await make_case(client, headers, project, scenario="Add a laptop to the cart")
    assert case["status"] == "draft" and case["latest_plan"] is None
    other = await client.post(
        f"{API}/projects/{project['id']}/suites", headers=headers, json={"name": "Checkout"}
    )
    moved = await client.patch(
        f"{API}/cases/{case['id']}", headers=headers, json={"suite_id": other.json()["id"]}
    )
    assert moved.json()["suite_id"] == other.json()["id"]

    found = (
        await client.get(f"{API}/projects/{project['id']}/cases?q=LAPTOP", headers=headers)
    ).json()
    assert [c["id"] for c in found] == [case["id"]]
    assert (
        await client.get(f"{API}/projects/{project['id']}/cases?q=missing", headers=headers)
    ).json() == []
    assert (
        len(
            (
                await client.get(
                    f"{API}/projects/{project['id']}/cases?status=draft", headers=headers
                )
            ).json()
        )
        == 1
    )
    assert (
        await client.get(f"{API}/projects/{project['id']}/cases?status=approved", headers=headers)
    ).json() == []


# ------------------------------------------------------------- AI generation


async def test_generate_plan_with_routed_models(ws: Client) -> None:
    client, headers = ws
    await route_ai(client, headers)
    project = await make_project(client, headers)
    case = await make_case(client, headers, project)

    generated = await client.post(
        f"{API}/cases/{case['id']}/plans/generate", headers=headers, json={}
    )
    assert generated.status_code == 201, generated.text
    body = generated.json()
    plan = body["latest_plan"]
    assert body["status"] == "planned"
    assert plan["source"] == "ai" and plan["status"] == "draft" and plan["revision"] == 1
    assert plan["analysis"]["requirements"]
    assert [r["task"] for r in plan["ai_requests"]] == ["requirement_analysis", "test_planning"]
    assert all(r["actual_model"] == "fake-pro-001" for r in plan["ai_requests"])
    assert plan["environment_name"] == "default"
    assert {i["code"] for i in plan["issues"]} == {
        "plan.variable_missing"
    }  # no test data stored yet

    # The planning prompt carries project context and variable names, never values.
    planning_call = FakeProvider.state.calls[1].request
    assert planning_call.schema_name == "TestPlan"
    assert "https://shop.example.com" in planning_call.prompt
    assert "<untrusted>" in planning_call.prompt


async def test_generation_requires_scenario_and_routing(ws: Client) -> None:
    client, headers = ws
    project = await make_project(client, headers)
    empty = await make_case(client, headers, project, scenario="")
    missing = await client.post(
        f"{API}/cases/{empty['id']}/plans/generate", headers=headers, json={}
    )
    assert missing.status_code == 422 and missing.json()["error"]["code"] == "test.scenario_missing"

    case = await make_case(client, headers, project)
    unrouted = await client.post(
        f"{API}/cases/{case['id']}/plans/generate", headers=headers, json={}
    )
    assert unrouted.status_code == 409
    assert unrouted.json()["error"]["code"] == "ai.routing_not_configured"


async def test_invalid_ai_plan_is_rejected_not_stored(ws: Client) -> None:
    client, headers = ws
    await route_ai(client, headers)
    project = await make_project(client, headers)
    case = await make_case(client, headers, project)
    bad_step = {"name": "x", "steps": [{"action": "click", "description": "no locator"}]}
    FakeProvider.state.script["fake"] = [CHECK_ANSWERS["RequirementAnalysis"], bad_step, bad_step]

    response = await client.post(
        f"{API}/cases/{case['id']}/plans/generate", headers=headers, json={}
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "ai.output_invalid"
    assert (await client.get(f"{API}/cases/{case['id']}", headers=headers)).json()[
        "latest_plan"
    ] is None


# --------------------------------------------------------- edit and approve


async def test_edit_approve_and_version_immutability(ws: Client) -> None:
    client, headers = ws
    await route_ai(client, headers)
    project = await make_project(client, headers)
    case = await make_case(client, headers, project)
    plan = (
        await client.post(f"{API}/cases/{case['id']}/plans/generate", headers=headers, json={})
    ).json()["latest_plan"]

    edited_body = plan_body(name="Sign in (edited)")
    edited = (
        await client.put(f"{API}/plans/{plan['id']}", headers=headers, json=edited_body)
    ).json()
    assert edited["latest_plan"]["source"] == "edited"
    assert edited["latest_plan"]["plan"]["name"] == "Sign in (edited)"

    approved = await client.post(f"{API}/plans/{plan['id']}/approve", headers=headers)
    assert approved.status_code == 201
    v1 = approved.json()
    assert v1["version"] == 1
    assert "def test_sign_in_edited(page: Page) -> None:" in v1["code_python"]
    assert 'env("LOGIN_PASSWORD")' in v1["code_typescript"]

    case_now = (await client.get(f"{API}/cases/{case['id']}", headers=headers)).json()
    assert case_now["status"] == "approved" and case_now["current_version_id"] == v1["id"]

    frozen = await client.put(
        f"{API}/plans/{plan['id']}", headers=headers, json=plan_body(name="Sneaky")
    )
    assert frozen.status_code == 409
    again = await client.post(f"{API}/plans/{plan['id']}/approve", headers=headers)
    assert again.status_code == 409

    draft = (
        await client.post(
            f"{API}/cases/{case['id']}/plans", headers=headers, json=plan_body(name="Second")
        )
    ).json()
    assert draft["latest_plan"]["revision"] == 2 and draft["latest_plan"]["source"] == "edited"
    v2 = (
        await client.post(f"{API}/plans/{draft['latest_plan']['id']}/approve", headers=headers)
    ).json()
    assert v2["version"] == 2

    first = (await client.get(f"{API}/versions/{v1['id']}", headers=headers)).json()
    assert first["plan"]["name"] == "Sign in (edited)" and first["code_python"] == v1["code_python"]
    listed = (await client.get(f"{API}/projects", headers=headers)).json()[0]
    assert listed["case_count"] == 1 and listed["approved_count"] == 1

    audit = [
        e["action"]
        for e in (await client.get(f"{API}/audit-logs?limit=50", headers=headers)).json()["items"]
    ]
    assert audit.count("test.version.approve") == 2 and "test.plan.generate" in audit


async def test_plans_with_errors_cannot_be_approved(ws: Client) -> None:
    client, headers = ws
    project = await make_project(client, headers)
    case = await make_case(client, headers, project)
    body = plan_body()
    body["plan"]["steps"][0]["value"] = "https://evil.example.org/phish"
    draft = (
        await client.post(f"{API}/cases/{case['id']}/plans", headers=headers, json=body)
    ).json()["latest_plan"]
    assert draft["source"] == "manual"
    assert any(
        i["code"] == "plan.domain_not_allowed" and i["severity"] == "error" for i in draft["issues"]
    )

    blocked = await client.post(f"{API}/plans/{draft['id']}/approve", headers=headers)
    assert blocked.status_code == 422
    assert blocked.json()["error"]["details"][0]["code"] == "plan.domain_not_allowed"


async def test_schema_violations_are_rejected_on_save(ws: Client) -> None:
    client, headers = ws
    project = await make_project(client, headers)
    case = await make_case(client, headers, project)
    body = plan_body()
    body["plan"]["steps"][1]["action"] = "execute_javascript"
    response = await client.post(f"{API}/cases/{case['id']}/plans", headers=headers, json=body)
    assert response.status_code == 422


async def test_deleting_an_approved_test(ws: Client) -> None:
    client, headers = ws
    project = await make_project(client, headers)
    case = await make_case(client, headers, project)
    plan = (
        await client.post(f"{API}/cases/{case['id']}/plans", headers=headers, json=plan_body())
    ).json()["latest_plan"]
    version = (await client.post(f"{API}/plans/{plan['id']}/approve", headers=headers)).json()
    assert (await client.delete(f"{API}/cases/{case['id']}", headers=headers)).status_code == 204
    assert (await client.get(f"{API}/versions/{version['id']}", headers=headers)).status_code == 404
    assert (
        await client.delete(f"{API}/projects/{project['id']}", headers=headers)
    ).status_code == 204
