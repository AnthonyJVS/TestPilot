"""Artifact retention: orphans and expired runs are removed, history stays."""

from __future__ import annotations

import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import update

from app.infrastructure.database.base import utcnow
from app.infrastructure.database.models import WorkflowExecution
from app.infrastructure.database.session import create_engine, create_session_factory
from app.maintenance import cleanup_artifacts
from tests.conftest import ClientFactory, bearer, register
from tests.integration.test_execution_api import approved_version, site_url, step, wait_finished

__all__ = ["site_url"]

API = "/api/v1"


async def test_cleanup_removes_orphans_and_expired_artifacts(
    client_factory: ClientFactory, tmp_path: Path, site_url: str, database_url: str
) -> None:
    root = tmp_path / "artifacts"
    async with client_factory(
        browser_allow_private_network=True, artifacts_dir=str(root)
    ) as client:
        headers = bearer((await register(client)).json()["access_token"])
        steps = [step("goto", "Open the app", value="/index.html")]
        _, version_id = await approved_version(client, headers, site_url, steps, with_data=False)
        started = (
            await client.post(f"{API}/versions/{version_id}/run", headers=headers, json={})
        ).json()
        run = await wait_finished(client, headers, started["id"])
        assert run["artifacts"]

        orphan = root / str(uuid.uuid4())
        orphan.mkdir()
        (orphan / "step-000.jpg").write_bytes(b"x" * 100)
        unrelated = root / "keep-me"
        unrelated.mkdir()

        engine = create_engine(database_url)
        factory = create_session_factory(engine)
        try:
            first = await cleanup_artifacts(factory, root, retention_days=30)
            assert first.orphan_directories == 1 and first.expired_runs == 0
            assert not orphan.exists() and unrelated.exists() and (root / run["id"]).exists()

            async with factory() as db:
                await db.execute(
                    update(WorkflowExecution)
                    .where(WorkflowExecution.id == uuid.UUID(run["id"]))
                    .values(finished_at=utcnow() - timedelta(days=40))
                )
                await db.commit()
            second = await cleanup_artifacts(factory, root, retention_days=30)
            assert second.expired_runs == 1 and second.bytes_freed > 0
            assert not (root / run["id"]).exists()
            assert (await cleanup_artifacts(factory, root, retention_days=0)).expired_runs == 0
        finally:
            await engine.dispose()

        after = (await client.get(f"{API}/executions/{run['id']}", headers=headers)).json()
        assert after["status"] == "passed" and after["artifacts"] == []
        events = (await client.get(f"{API}/executions/{run['id']}/events", headers=headers)).json()
        assert events  # history stays
