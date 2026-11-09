import { Link } from "react-router";

import { ErrorState } from "@/components/common/ErrorState";
import { PageHeader } from "@/components/common/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { ExecutionsList } from "@/features/executions/ExecutionsList";

import { ActivityList } from "./ActivityList";
import { useAuditLogs } from "./api";
import { InstrumentStrip } from "./InstrumentStrip";
import { PreflightChecklist } from "./PreflightChecklist";

function RecentActivity() {
  const { data, error, isPending, refetch } = useAuditLogs(6);
  const entries = data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <section aria-labelledby="activity-heading" className="rounded-panel border border-border bg-panel">
      <div className="flex items-baseline justify-between border-b border-border px-5 py-4">
        <h2 id="activity-heading" className="text-[15px] font-semibold">
          Account activity
        </h2>
        <Link to="/settings" className="text-[13px] text-muted hover:text-text">
          View all
        </Link>
      </div>
      <div className="px-5">
        {isPending ? (
          <div className="space-y-3 py-4">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-9" />
            ))}
          </div>
        ) : error ? (
          <div className="py-4">
            <ErrorState error={error} onRetry={() => void refetch()} />
          </div>
        ) : entries.length === 0 ? (
          <p className="py-6 text-sm text-muted">No activity recorded yet.</p>
        ) : (
          <ActivityList entries={entries} />
        )}
      </div>
    </section>
  );
}

function ExecutionsPanel() {
  return (
    <section aria-labelledby="runs-heading" className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h2 id="runs-heading" className="text-[15px] font-semibold">
          Recent runs
        </h2>
        <Link to="/executions" className="text-[13px] text-beacon hover:underline">
          View all
        </Link>
      </div>
      <ExecutionsList limit={5} emptyHint="No runs yet. Approve a test plan, then choose Run test." />
    </section>
  );
}

export function DashboardPage() {
  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <PageHeader title="Dashboard" description="Live system status, setup progress and recent account activity." />
      <InstrumentStrip />
      <div className="grid gap-6 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <PreflightChecklist />
        </div>
        <div className="space-y-6 lg:col-span-2">
          <RecentActivity />
          <ExecutionsPanel />
        </div>
      </div>
    </div>
  );
}
