"""AI providers, routing, routing checks and orchestration policies through the HTTP API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.infrastructure.database.models import AICredential
from app.infrastructure.database.session import create_engine, create_session_factory
from app.services.ai.errors import (
    AIAuthError,
    AIQuotaExhaustedError,
    AIRateLimitError,
)
from app.services.ai.types import TaskCategory
from tests.conftest import SLEEPS, ClientFactory, bearer, register
from tests.fakes import FakeProvider, FakeState, fake_registry

API = "/api/v1/ai"
TASKS = [t.value for t in TaskCategory]


@pytest.fixture(autouse=True)
def _reset_fake() -> None:
    FakeProvider.state = FakeState()
    SLEEPS.clear()


@pytest.fixture
async def ai(
    client_factory: ClientFactory,
) -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, str]]]:
    async with client_factory(registry=fake_registry()) as client:
        token = (await register(client)).json()["access_token"]
        yield client, bearer(token)


async def connect(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    provider_type: str = "fake",
    key: str = "fake-key-123456",
) -> dict[str, Any]:
    created = await client.post(
        f"{API}/providers",
        headers=headers,
        json={"provider_type": provider_type, "name": f"My {provider_type}", "api_key": key},
    )
    assert created.status_code == 201, created.text
    tested = await client.post(f"{API}/providers/{created.json()['id']}/test", headers=headers)
    assert tested.status_code == 200 and tested.json()["ok"], tested.text
    provider: dict[str, Any] = tested.json()["provider"]
    return provider


def model_id(provider: dict[str, Any], name: str) -> str:
    return next(m["id"] for m in provider["models"] if m["model_id"] == name)


async def set_routing(
    client: httpx.AsyncClient, headers: dict[str, str], **body: Any
) -> httpx.Response:
    payload = {"mode": "simple", "task_routes": {}, "fallback_enabled": False, **body}
    return await client.put(f"{API}/routing", headers=headers, json=payload)


# ------------------------------------------------------------------ provider catalog


async def test_provider_catalog_marks_planned_providers(
    ai: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = ai
    types = {
        t["type_id"]: t for t in (await client.get(f"{API}/provider-types", headers=headers)).json()
    }
    assert {"gemini", "anthropic", "openai"} <= {
        k for k, v in types.items() if v["status"] == "available"
    }
    for planned in (
        "deepseek",
        "mistral",
        "xai",
        "openrouter",
        "azure_openai",
        "aws_bedrock",
        "ollama",
        "lmstudio",
    ):
        assert types[planned]["status"] == "planned"
    assert types["ollama"]["data_location"] == "local"
    assert types["gemini"]["data_location"] == "external"


# ----------------------------------------------------------------- credentials


async def test_api_key_is_encrypted_and_never_returned(
    ai: tuple[httpx.AsyncClient, dict[str, str]], database_url: str
) -> None:
    client, headers = ai
    secret = "fake-secret-key-ABCD"
    created = await client.post(
        f"{API}/providers",
        headers=headers,
        json={"provider_type": "fake", "name": "Primary", "api_key": secret},
    )
    assert created.status_code == 201
    assert secret not in created.text
    assert created.json()["credential"]["key_hint"] == "ABCD"
    listed = await client.get(f"{API}/providers", headers=headers)
    assert secret not in listed.text

    engine = create_engine(database_url)
    async with create_session_factory(engine)() as session:
        stored = (await session.execute(select(AICredential))).scalar_one()
        assert secret.encode() not in stored.ciphertext
        assert stored.key_id == "t1"
    await engine.dispose()

    audit = (await client.get("/api/v1/audit-logs", headers=headers)).json()["items"]
    assert any(e["action"] == "ai.provider.create" for e in audit)
    assert secret not in str(audit)


async def test_rotated_key_is_used_for_later_calls(
    ai: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = ai
    provider = await connect(client, headers, key="first-key-0001")
    await set_routing(client, headers, default_model_id=model_id(provider, "fake-pro"))

    rotated = await client.put(
        f"{API}/providers/{provider['id']}/credential",
        headers=headers,
        json={"api_key": "second-key-0002"},
    )
    assert rotated.status_code == 200
    assert rotated.json()["credential"]["key_hint"] == "0002"
    assert rotated.json()["credential"]["rotated_at"] is not None

    assert (
        await client.post(f"{API}/routing/check/report_generation", headers=headers)
    ).status_code == 200
    assert FakeProvider.state.calls[-1].api_key == "second-key-0002"

    deleted = await client.delete(f"{API}/providers/{provider['id']}/credential", headers=headers)
    assert deleted.json()["credential"] is None
    blocked = await client.post(f"{API}/routing/check/report_generation", headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "ai.credential_missing"


async def test_creation_rules(ai: tuple[httpx.AsyncClient, dict[str, str]]) -> None:
    client, headers = ai
    planned = await client.post(
        f"{API}/providers",
        headers=headers,
        json={"provider_type": "mistral", "name": "M", "api_key": "x" * 20},
    )
    assert planned.status_code == 400
    assert planned.json()["error"]["code"] == "ai.provider_type_unavailable"

    no_key = await client.post(
        f"{API}/providers", headers=headers, json={"provider_type": "fake", "name": "K"}
    )
    assert no_key.status_code == 409

    await client.post(
        f"{API}/providers",
        headers=headers,
        json={"provider_type": "fake", "name": "Dup", "api_key": "k" * 16},
    )
    duplicate = await client.post(
        f"{API}/providers",
        headers=headers,
        json={"provider_type": "fake", "name": "Dup", "api_key": "k" * 16},
    )
    assert duplicate.status_code == 409

    ssrf = await client.post(
        f"{API}/providers",
        headers=headers,
        json={
            "provider_type": "openai",
            "name": "Proxy",
            "api_key": "k" * 16,
            "base_url": "http://169.254.169.254/v1",
        },
    )
    assert ssrf.status_code == 422
    assert ssrf.json()["error"]["code"] == "ai.base_url_rejected"


async def test_other_users_cannot_touch_my_providers(
    client_factory: ClientFactory,
) -> None:
    async with client_factory(registry=fake_registry()) as client:
        alice = bearer((await register(client)).json()["access_token"])
        provider = await connect(client, alice)
        client.cookies.clear()
        bob = bearer(
            (await register(client, email="bob@example.com", display_name="Bob")).json()[
                "access_token"
            ]
        )

        assert (
            await client.get(f"{API}/providers/{provider['id']}", headers=bob)
        ).status_code == 404
        assert (
            await client.delete(f"{API}/providers/{provider['id']}", headers=bob)
        ).status_code == 404
        assert (
            await client.post(f"{API}/providers/{provider['id']}/test", headers=bob)
        ).status_code == 404
        steal = await set_routing(client, bob, default_model_id=model_id(provider, "fake-pro"))
        assert steal.status_code == 404
        assert (await client.get(f"{API}/providers", headers=bob)).json() == []


# ------------------------------------------------------------------ model catalog


async def test_connection_test_discovers_models_and_reports_failures(
    ai: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = ai
    provider = await connect(client, headers)
    assert provider["status"] == "connected"
    assert {m["model_id"] for m in provider["models"]} == {"fake-pro", "fake-text"}
    text_model = next(m for m in provider["models"] if m["model_id"] == "fake-text")
    assert text_model["capabilities"]["vision"] == {
        "status": "unsupported",
        "source": "provider_metadata",
    }
    assert text_model["capabilities"]["structured_output"]["status"] == "unknown"

    FakeProvider.state.list_errors["fake"] = AIAuthError()
    failed = (await client.post(f"{API}/providers/{provider['id']}/test", headers=headers)).json()
    assert failed["ok"] is False
    assert failed["provider"]["status"] == "error"
    assert "API key" in failed["provider"]["last_error"]


async def test_manual_model_ids(ai: tuple[httpx.AsyncClient, dict[str, str]]) -> None:
    client, headers = ai
    provider = await connect(client, headers)
    added = await client.post(
        f"{API}/providers/{provider['id']}/models",
        headers=headers,
        json={"model_id": "fake-preview-2026"},
    )
    assert added.status_code == 201
    assert added.json()["source"] == "manual"
    assert all(c["status"] == "unknown" for c in added.json()["capabilities"].values())
    again = await client.post(
        f"{API}/providers/{provider['id']}/models",
        headers=headers,
        json={"model_id": "fake-preview-2026"},
    )
    assert again.status_code == 409
    bad = await client.post(
        f"{API}/providers/{provider['id']}/models", headers=headers, json={"model_id": "has spaces"}
    )
    assert bad.status_code == 422
    assert (
        await client.delete(f"{API}/models/{added.json()['id']}", headers=headers)
    ).status_code == 204


# ------------------------------------------------------------------------ routing


async def test_simple_mode_routes_every_task_to_one_model(
    ai: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = ai
    empty = (await client.get(f"{API}/routing", headers=headers)).json()
    assert all(r["model"] is None and r["issues"] for r in empty["effective"])

    provider = await connect(client, headers)
    routing = (
        await set_routing(client, headers, default_model_id=model_id(provider, "fake-pro"))
    ).json()
    assert [r["task"] for r in routing["effective"]] == TASKS
    assert {r["model"]["model_id"] for r in routing["effective"]} == {"fake-pro"}
    assert {r["source"] for r in routing["effective"]} == {"default"}
    visual = next(r for r in routing["effective"] if r["task"] == "visual_analysis")
    assert "vision" in visual["required_capabilities"]
    assert visual["warnings"]  # vision not verified yet


async def test_single_key_powers_every_task_category(
    ai: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    """Milestone 2 acceptance: one provider connection runs all seven task categories."""
    client, headers = ai
    provider = await connect(client, headers)
    await set_routing(client, headers, default_model_id=model_id(provider, "fake-pro"))

    for task in TASKS:
        result = (await client.post(f"{API}/routing/check/{task}", headers=headers)).json()
        assert result["status"] == "passed", result
        assert result["provider_type"] == "fake"
        assert result["actual_model"] == "fake-pro-001"
        assert result["total_tokens"] == 18

    assert len(FakeProvider.state.calls) == 7
    visual_call = next(
        c for c in FakeProvider.state.calls if c.request.schema_name == "ColourAnswer"
    )
    assert visual_call.request.images and visual_call.request.images[0].mime_type == "image/png"

    refreshed = (await client.get(f"{API}/providers/{provider['id']}", headers=headers)).json()
    pro = next(m for m in refreshed["models"] if m["model_id"] == "fake-pro")
    assert pro["capabilities"]["vision"] == {"status": "supported", "source": "probe"}
    assert pro["capabilities"]["structured_output"] == {"status": "supported", "source": "probe"}

    log = (await client.get(f"{API}/requests?limit=50", headers=headers)).json()["items"]
    assert len(log) == 7
    assert {e["origin"] for e in log} == {"routing_check"}
    assert all(e["status"] == "success" and e["requested_model"] == "fake-pro" for e in log)


async def test_advanced_mode_routes_tasks_to_different_providers(
    ai: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = ai
    first = await connect(client, headers, "fake", key="key-for-first-1")
    second = await connect(client, headers, "fake2", key="key-for-second-2")
    routing = await set_routing(
        client,
        headers,
        mode="advanced",
        default_model_id=model_id(first, "fake-pro"),
        task_routes={"code_generation": model_id(second, "fake2-pro")},
    )
    effective = {r["task"]: r for r in routing.json()["effective"]}
    assert effective["code_generation"]["model"]["provider_type"] == "fake2"
    assert effective["code_generation"]["source"] == "task_route"
    assert effective["test_planning"]["model"]["provider_type"] == "fake"

    await client.post(f"{API}/routing/check/code_generation", headers=headers)
    await client.post(f"{API}/routing/check/test_planning", headers=headers)
    calls = FakeProvider.state.calls
    assert (calls[0].provider_type, calls[0].api_key) == ("fake2", "key-for-second-2")
    assert (calls[1].provider_type, calls[1].api_key) == ("fake", "key-for-first-1")

    # Back to simple mode: stored task routes are kept but ignored.
    simple = await set_routing(
        client,
        headers,
        default_model_id=model_id(first, "fake-pro"),
        task_routes={"code_generation": model_id(second, "fake2-pro")},
    )
    assert {r["model"]["provider_type"] for r in simple.json()["effective"]} == {"fake"}


async def test_visual_task_refuses_a_model_without_vision(
    ai: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = ai
    provider = await connect(client, headers)
    routing = (
        await set_routing(client, headers, default_model_id=model_id(provider, "fake-text"))
    ).json()
    visual = next(r for r in routing["effective"] if r["task"] == "visual_analysis")
    assert visual["issues"] and "vision" in visual["issues"][0]

    response = await client.post(f"{API}/routing/check/visual_analysis", headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ai.capability_missing"
    assert FakeProvider.state.calls == []


# --------------------------------------------------------------- retry / fallback


async def test_transient_errors_are_retried_and_recorded(
    ai: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = ai
    provider = await connect(client, headers)
    await set_routing(client, headers, default_model_id=model_id(provider, "fake-pro"))
    FakeProvider.state.script["fake"] = [AIRateLimitError(retry_after=3)]

    result = (await client.post(f"{API}/routing/check/test_planning", headers=headers)).json()
    assert result["status"] == "passed"
    assert SLEEPS == [3]
    entry = (await client.get(f"{API}/requests", headers=headers)).json()["items"][0]
    assert entry["attempts"] == 2
    assert entry["retry_history"][0]["error"] == "ai.rate_limited"
    assert entry["retry_history"][0]["waited_seconds"] == 3


async def test_long_rate_limit_waits_pause_instead_of_blocking(
    ai: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = ai
    provider = await connect(client, headers)
    await set_routing(client, headers, default_model_id=model_id(provider, "fake-pro"))
    FakeProvider.state.script["fake"] = [AIRateLimitError(retry_after=600)]

    result = (await client.post(f"{API}/routing/check/test_planning", headers=headers)).json()
    assert result["status"] == "error"
    assert SLEEPS == []
    assert len(FakeProvider.state.calls) == 1


async def test_quota_exhaustion_pauses_without_fallback(
    ai: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = ai
    first = await connect(client, headers, "fake")
    await connect(client, headers, "fake2")
    await set_routing(client, headers, default_model_id=model_id(first, "fake-pro"))
    FakeProvider.state.script["fake"] = [AIQuotaExhaustedError()]

    result = (await client.post(f"{API}/routing/check/test_planning", headers=headers)).json()
    assert result["status"] == "error"
    assert "quota" in result["message"].lower()
    assert [c.provider_type for c in FakeProvider.state.calls] == [
        "fake"
    ]  # never switched silently
    entry = (await client.get(f"{API}/requests", headers=headers)).json()["items"][0]
    assert entry["status"] == "error" and entry["error_code"] == "ai.quota_exhausted"
    assert entry["fallback_used"] is False


async def test_enabled_fallback_is_used_and_recorded(
    ai: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = ai
    first = await connect(client, headers, "fake")
    second = await connect(client, headers, "fake2")
    await set_routing(
        client,
        headers,
        default_model_id=model_id(first, "fake-pro"),
        fallback_enabled=True,
        fallback_model_id=model_id(second, "fake2-pro"),
    )
    FakeProvider.state.script["fake"] = [AIQuotaExhaustedError()]

    result = (await client.post(f"{API}/routing/check/test_planning", headers=headers)).json()
    assert result["status"] == "passed"
    assert result["provider_type"] == "fake2"
    entry = (await client.get(f"{API}/requests", headers=headers)).json()["items"][0]
    assert entry["fallback_used"] is True
    assert entry["requested_provider_type"] == "fake" and entry["requested_model"] == "fake-pro"
    assert entry["actual_provider_type"] == "fake2" and entry["actual_model"] == "fake2-pro-001"
    assert entry["fallback_reason"].startswith("ai.quota_exhausted")
    assert any(h.get("event") == "fallback" for h in entry["retry_history"])


async def test_permanent_errors_never_fall_back(
    ai: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = ai
    first = await connect(client, headers, "fake")
    second = await connect(client, headers, "fake2")
    await set_routing(
        client,
        headers,
        default_model_id=model_id(first, "fake-pro"),
        fallback_enabled=True,
        fallback_model_id=model_id(second, "fake2-pro"),
    )
    FakeProvider.state.script["fake"] = [AIAuthError()]

    result = (await client.post(f"{API}/routing/check/test_planning", headers=headers)).json()
    assert result["status"] == "error"
    assert [c.provider_type for c in FakeProvider.state.calls] == ["fake"]


async def test_fallback_settings_are_validated(
    ai: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = ai
    provider = await connect(client, headers)
    pro = model_id(provider, "fake-pro")
    missing = await set_routing(client, headers, default_model_id=pro, fallback_enabled=True)
    assert missing.status_code == 422
    same = await set_routing(
        client, headers, default_model_id=pro, fallback_enabled=True, fallback_model_id=pro
    )
    assert same.status_code == 422


# -------------------------------------------------------------- output validation


async def test_invalid_structured_output_gets_one_repair_attempt(
    ai: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = ai
    provider = await connect(client, headers)
    await set_routing(client, headers, default_model_id=model_id(provider, "fake-pro"))

    FakeProvider.state.script["fake"] = ["not json at all"]
    repaired = (await client.post(f"{API}/routing/check/report_generation", headers=headers)).json()
    assert repaired["status"] == "passed"
    assert "previous answer was rejected" in FakeProvider.state.calls[-1].request.prompt

    FakeProvider.state.script["fake"] = ['{"wrong": 1}', '```json\n{"still": "wrong"}\n```']
    failed = (await client.post(f"{API}/routing/check/report_generation", headers=headers)).json()
    assert failed["status"] == "error"
    entry = (await client.get(f"{API}/requests", headers=headers)).json()["items"][0]
    assert entry["error_code"] == "ai.output_invalid"


# ------------------------------------------------------------ limits & privacy


async def test_daily_request_limit_pauses_ai_work(
    ai: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = ai
    provider = await connect(client, headers)
    await set_routing(
        client, headers, default_model_id=model_id(provider, "fake-pro"), daily_request_limit=1
    )
    assert (
        await client.post(f"{API}/routing/check/test_planning", headers=headers)
    ).status_code == 200
    blocked = await client.post(f"{API}/routing/check/test_planning", headers=headers)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "ai.usage_limit_reached"
    routing = (await client.get(f"{API}/routing", headers=headers)).json()
    assert routing["requests_today"] == 1


async def test_payload_previews_are_optional_and_redacted(
    ai: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = ai
    provider = await connect(client, headers)
    await set_routing(client, headers, default_model_id=model_id(provider, "fake-pro"))
    await client.post(f"{API}/routing/check/test_planning", headers=headers)
    entry = (await client.get(f"{API}/requests", headers=headers)).json()["items"][0]
    assert "laptop" in entry["request_preview"]["prompt"]
    assert "untrusted" in entry["request_preview"]["system"].lower()
    assert entry["response_preview"]["output"]["steps"]

    await set_routing(
        client,
        headers,
        default_model_id=model_id(provider, "fake-pro"),
        store_payload_previews=False,
    )
    await client.post(f"{API}/routing/check/test_planning", headers=headers)
    latest = (await client.get(f"{API}/requests", headers=headers)).json()["items"][0]
    assert latest["request_preview"] is None and latest["response_preview"] is None


async def test_deleting_a_provider_clears_routes_to_its_models(
    ai: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = ai
    provider = await connect(client, headers)
    await set_routing(client, headers, default_model_id=model_id(provider, "fake-pro"))
    assert (
        await client.delete(f"{API}/providers/{provider['id']}", headers=headers)
    ).status_code == 204
    routing = (await client.get(f"{API}/routing", headers=headers)).json()
    assert routing["default_model_id"] is None
    assert all(r["model"] is None for r in routing["effective"])
