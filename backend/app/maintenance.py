"""Housekeeping: artifact retention (milestone 8).

``python -m app.maintenance cleanup-artifacts`` removes

* artifact directories that belong to no execution any more (deleted projects or tests), and
* the files of runs that finished more than ``ARTIFACT_RETENTION_DAYS`` ago (0 keeps them),
  together with their artifact records. Run records, steps and events stay in the history.

In development (inline mode) the API also runs it at start-up and every six hours. With Docker
Compose, run it in the ``worker`` service (it mounts the artifacts volume read-write), e.g. daily
from cron.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.database.base import utcnow
from app.infrastructure.database.models import ExecutionArtifact, WorkflowExecution

logger = logging.getLogger(__name__)


@dataclass
class CleanupResult:
    orphan_directories: int = 0
    expired_runs: int = 0
    bytes_freed: int = 0


def _size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _remove_orphans(root: Path, known: set[str]) -> tuple[int, int]:
    removed = freed = 0
    if not root.is_dir():
        return removed, freed
    for directory in root.iterdir():
        try:
            uuid.UUID(directory.name)
        except ValueError:
            continue  # never touch anything that is not an execution directory
        if directory.is_dir() and directory.name not in known:
            freed += _size(directory)
            shutil.rmtree(directory, ignore_errors=True)
            removed += 1
    return removed, freed


def _remove_directories(root: Path, names: list[str]) -> int:
    freed = 0
    for name in names:
        directory = root / name
        if directory.is_dir():
            freed += _size(directory)
            shutil.rmtree(directory, ignore_errors=True)
    return freed


async def cleanup_artifacts(
    session_factory: async_sessionmaker[AsyncSession], root: Path, retention_days: int
) -> CleanupResult:
    result = CleanupResult()
    root = await asyncio.to_thread(root.resolve)
    async with session_factory() as db:
        known = {str(i) for i in (await db.execute(select(WorkflowExecution.id))).scalars()}
        result.orphan_directories, result.bytes_freed = await asyncio.to_thread(
            _remove_orphans, root, known
        )
        if retention_days > 0:
            cutoff = utcnow() - timedelta(days=retention_days)
            expired = list(
                (
                    await db.execute(
                        select(WorkflowExecution.id)
                        .join(
                            ExecutionArtifact,
                            ExecutionArtifact.execution_id == WorkflowExecution.id,
                        )
                        .where(
                            WorkflowExecution.finished_at.is_not(None),
                            WorkflowExecution.finished_at < cutoff,
                        )
                        .distinct()
                    )
                ).scalars()
            )
            if expired:
                result.bytes_freed += await asyncio.to_thread(
                    _remove_directories, root, [str(i) for i in expired]
                )
                await db.execute(
                    delete(ExecutionArtifact).where(ExecutionArtifact.execution_id.in_(expired))
                )
                await db.commit()
                result.expired_runs = len(expired)
    if result.orphan_directories or result.expired_runs:
        logger.info(
            "Artifact cleanup: %d orphan directories, %d expired runs, %d bytes freed",
            result.orphan_directories,
            result.expired_runs,
            result.bytes_freed,
        )
    return result


async def _main() -> None:
    from app.core.config import get_settings
    from app.infrastructure.database.session import (
        create_engine,
        create_session_factory,
    )

    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        result = await cleanup_artifacts(
            create_session_factory(engine),
            Path(settings.artifacts_dir),
            settings.artifact_retention_days,
        )
    finally:
        await engine.dispose()
    print(
        f"Removed {result.orphan_directories} orphan directories and the artifacts of "
        f"{result.expired_runs} expired runs ({result.bytes_freed} bytes)."
    )


if __name__ == "__main__":
    if sys.argv[1:] != ["cleanup-artifacts"]:
        sys.exit("usage: python -m app.maintenance cleanup-artifacts")
    asyncio.run(_main())
