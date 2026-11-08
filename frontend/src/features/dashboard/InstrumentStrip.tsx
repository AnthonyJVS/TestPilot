import type { ReactNode } from "react";

import { ErrorState } from "@/components/common/ErrorState";
import { StatusIndicator, type IndicatorState } from "@/components/common/StatusIndicator";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDuration } from "@/lib/utils";

import { useSystemStatus } from "./api";

function Gauge({ name, state, reading, detail }: {
  name: string;
  state: IndicatorState;
  reading: ReactNode;
  detail: ReactNode;
}) {
  return (
    <div className="min-w-0 px-5 py-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[13px] font-medium text-muted [font-stretch:100%]">{name}</h3>
        <StatusIndicator state={state} className="text-xs" />
      </div>
      <p className="mt-2 truncate text-xl font-semibold tabular-nums">{reading}</p>
      <p className="mt-0.5 truncate text-[13px] text-faint">{detail}</p>
    </div>
  );
}

/** Live readings from GET /system/status, refreshed every 15 seconds. */
export function InstrumentStrip() {
  const { data, error, isPending, refetch, dataUpdatedAt } = useSystemStatus();

  if (isPending) {
    return <Skeleton className="h-[106px] w-full rounded-panel" />;
  }
  if (error && !data) {
    return <ErrorState error={error} title="System status is unavailable" onRetry={() => void refetch()} />;
  }

  const db = data.database;
  const redis = data.redis;
  const redisReading =
    redis.status === "ok" ? `${redis.latency_ms} ms` : redis.status === "not_configured" ? "Off" : "Down";
  const redisDetail =
    redis.status === "not_configured"
      ? "In-memory rate limiting (dev only)"
      : redis.status === "ok"
        ? "Rate limiting and queues"
        : (redis.detail ?? "Connection failed");

  return (
    <section aria-labelledby="instruments-heading">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 id="instruments-heading" className="text-[15px] font-semibold">
          System status
        </h2>
        <p className="text-xs text-faint" aria-live="polite">
          Checked {new Date(dataUpdatedAt).toLocaleTimeString()}
        </p>
      </div>
      {/* Hairline separators come from the 1px gap over the border-coloured backdrop. */}
      <div className="grid gap-px overflow-hidden rounded-panel border border-border bg-border sm:grid-cols-2 xl:grid-cols-4 [&>*]:bg-panel">
        <Gauge
          name="API"
          state="ok"
          reading={`v${data.version}`}
          detail={`Up ${formatDuration(data.uptime_seconds)}, ${data.environment}`}
        />
        <Gauge
          name="Database"
          state={db.status}
          reading={db.status === "ok" ? `${db.latency_ms} ms` : "Down"}
          detail={`${db.dialect === "postgresql" ? "PostgreSQL" : db.dialect === "sqlite" ? "SQLite (dev)" : db.dialect}`}
        />
        <Gauge
          name="Schema"
          state={db.migration_revision ? "ok" : "error"}
          reading={db.migration_revision ? `rev ${db.migration_revision}` : "Unknown"}
          detail={db.migration_revision ? "Migrations applied" : "Run alembic upgrade head"}
        />
        <Gauge name="Redis" state={redis.status} reading={redisReading} detail={redisDetail} />
      </div>
    </section>
  );
}
