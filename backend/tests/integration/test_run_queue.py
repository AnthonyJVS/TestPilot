"""When the job queue is down, starting a run is an infrastructure error (503), not a bad request."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from tests.conftest import ClientFactory, bearer, register

API = "/api/v1"


async def _broken_enqueue(execution_id: uuid.UUID) -> None:
    raise ModuleNotFoundError("No module named 'packaging'")


def _break_queue(client: httpx.AsyncClient) -> None:
    app: Any = client._transport.app  # type: ignore[attr-defined]
    app.state.execution.jobs.enqueue = _broken_enqueue


async def _project(client: httpx.AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.post(
        f"{API}/projects",
        headers=headers,
        json={"name": f"Queue {uuid.uuid4().hex[:6]}", "base_url": "https://example.com"},
    )
    assert response.status_code == 201, response.text
    project: dict[str, Any] = response.json()
    return project


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def service_errors() -> Iterator[_Collect]:
    # Attached to the services' own loggers: the app's logging setup replaces root handlers.
    handler = _Collect()
    loggers = [
        logging.getLogger("app.services.execution.execution_service"),
        logging.getLogger("app.services.workflows.workflow_service"),
    ]
    for logger in loggers:
        logger.addHandler(handler)
    yield handler
    for logger in loggers:
        logger.removeHandler(handler)


async def test_runs_answer_503_and_are_marked_failed_when_the_queue_is_down(
    client_factory: ClientFactory, service_errors: _Collect
) -> None:
    async with client_factory() as client:
        headers = bearer((await register(client)).json()["access_token"])
        project = await _project(client, headers)
        suite = (await client.get(f"{API}/projects/{project['id']}/suites", headers=headers)).json()
        case = (
            await client.post(
                f"{API}/projects/{project['id']}/cases",
                headers=headers,
                json={"suite_id": suite[0]["id"], "name": "Open"},
            )
        ).json()
        plan = {"name": "Open", "steps": [{"action": "goto", "description": "Open", "value": "/"}]}
        draft = (
            await client.post(
                f"{API}/cases/{case['id']}/plans", headers=headers, json={"plan": plan}
            )
        ).json()
        version = (
            await client.post(f"{API}/plans/{draft['latest_plan']['id']}/approve", headers=headers)
        ).json()
        workflow = (
            await client.post(
                f"{API}/projects/{project['id']}/workflows", headers=headers, json={"name": "Flow"}
            )
        ).json()
        graph = {
            "nodes": [{"id": "in", "type": "data.input", "label": "", "config": {"text": "hi"}}],
            "edges": [],
        }
        saved = await client.post(
            f"{API}/workflows/{workflow['id']}/versions", headers=headers, json={"graph": graph}
        )
        assert saved.status_code == 201, saved.text

        _break_queue(client)
        for path in (f"/versions/{version['id']}/run", f"/workflows/{workflow['id']}/run"):
            response = await client.post(f"{API}{path}", headers=headers, json={})
            assert response.status_code == 503, (path, response.text)
            error = response.json()["error"]
            assert error["code"] == "run.queue_unavailable"
            assert "packaging" not in error["message"]  # internals stay in the server log

        # The real cause is in the server log, and nothing is left waiting forever.
        causes = [str(r.exc_info[1]) for r in service_errors.records if r.exc_info]
        assert causes == ["No module named 'packaging'"] * 2
        runs = (await client.get(f"{API}/executions", headers=headers)).json()
        assert sorted(r["kind"] for r in runs) == ["test_run", "workflow"]
        assert {r["status"] for r in runs} == {"error"}
