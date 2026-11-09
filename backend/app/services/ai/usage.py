"""AI usage dashboard: aggregates of the request log for one account (milestone 8)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import AIRequest, AIRoutingSettings


def _p95(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]


def _avg(values: list[int]) -> int | None:
    return int(sum(values) / len(values)) if values else None


async def usage_summary(db: AsyncSession, owner_id: uuid.UUID, days: int) -> dict[str, Any]:
    today = datetime.now(UTC).date()
    first = today - timedelta(days=days - 1)
    since = datetime.combine(first, datetime.min.time(), tzinfo=UTC)
    rows = list(
        (
            await db.execute(
                select(AIRequest).where(
                    AIRequest.owner_id == owner_id, AIRequest.started_at >= since
                )
            )
        ).scalars()
    )
    per_day: dict[date, dict[str, int]] = {
        first + timedelta(days=i): {"requests": 0, "succeeded": 0, "failed": 0, "tokens": 0}
        for i in range(days)
    }
    models: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"requests": 0, "failed": 0, "tokens": 0, "fallbacks": 0, "latencies": []}
    )
    tasks: dict[str, dict[str, int]] = defaultdict(
        lambda: {"requests": 0, "tokens": 0, "failed": 0}
    )
    origins: dict[str, int] = defaultdict(int)
    latencies: list[int] = []
    for row in rows:
        ok = row.status == "success"
        tokens = row.total_tokens or 0
        day = per_day.get(row.started_at.astimezone(UTC).date())
        if day is not None:
            day["requests"] += 1
            day["succeeded" if ok else "failed"] += 1
            day["tokens"] += tokens
        provider = row.actual_provider_type or row.requested_provider_type
        model = row.actual_model or row.requested_model
        stats = models[(provider, model)]
        stats["requests"] += 1
        stats["failed"] += 0 if ok else 1
        stats["tokens"] += tokens
        stats["fallbacks"] += 1 if row.fallback_used else 0
        if row.latency_ms is not None and ok:
            stats["latencies"].append(row.latency_ms)
            latencies.append(row.latency_ms)
        task = tasks[row.task or "other"]
        task["requests"] += 1
        task["tokens"] += tokens
        task["failed"] += 0 if ok else 1
        origins[row.origin] += 1

    routing = await db.scalar(
        select(AIRoutingSettings).where(AIRoutingSettings.owner_id == owner_id)
    )
    midnight = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
    requests_today = sum(1 for r in rows if r.started_at >= midnight)
    return {
        "days": [{"date": d.isoformat(), **values} for d, values in per_day.items()],
        "models": sorted(
            (
                {
                    "provider_type": provider,
                    "model": model,
                    "requests": s["requests"],
                    "failed": s["failed"],
                    "tokens": s["tokens"],
                    "fallbacks": s["fallbacks"],
                    "avg_latency_ms": _avg(s["latencies"]),
                    "p95_latency_ms": _p95(s["latencies"]),
                }
                for (provider, model), s in models.items()
            ),
            key=lambda m: -m["requests"],
        ),
        "tasks": sorted(
            ({"task": task, **values} for task, values in tasks.items()),
            key=lambda t: -t["requests"],
        ),
        "origins": dict(origins),
        "totals": {
            "requests": len(rows),
            "succeeded": sum(1 for r in rows if r.status == "success"),
            "failed": sum(1 for r in rows if r.status != "success"),
            "tokens": sum(r.total_tokens or 0 for r in rows),
            "fallbacks": sum(1 for r in rows if r.fallback_used),
            "avg_latency_ms": _avg(latencies),
            "p95_latency_ms": _p95(latencies),
        },
        "requests_today": requests_today,
        "daily_limit": routing.daily_request_limit if routing else None,
    }
