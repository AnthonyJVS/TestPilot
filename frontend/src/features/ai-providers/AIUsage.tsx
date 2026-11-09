import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { ErrorState } from "@/components/common/ErrorState";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { apiRequest } from "@/lib/api-client";
import type { components } from "@/types/openapi";

type Usage = components["schemas"]["AIUsageOut"];

const TASKS: Record<string, string> = {
  requirement_analysis: "Requirement analysis",
  test_planning: "Test planning",
  code_generation: "Code generation",
  failure_analysis: "Failure analysis",
  visual_analysis: "Visual analysis",
  test_repair: "Test repair",
  report_generation: "Report generation",
  other: "Other",
};

const number = new Intl.NumberFormat();
const ms = (value: number | null | undefined) => (value == null ? "—" : value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(1)} s`);

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-control border border-border bg-raised/40 px-4 py-3">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-0.5 text-[22px] font-semibold tabular-nums">{value}</p>
      {note ? <p className="text-[11px] text-faint">{note}</p> : null}
    </div>
  );
}

/** Requests per day: one series, so one hue and no legend; hover shows the details. */
function DailyBars({ days }: { days: Usage["days"] }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...days.map((d) => d.requests));
  const active = hover !== null ? days[hover] : undefined;
  return (
    <figure className="space-y-2">
      <figcaption className="flex items-baseline justify-between text-xs text-muted">
        <span>Requests per day (UTC)</span>
        <span className="tabular-nums text-faint">max {max}</span>
      </figcaption>
      <div className="relative">
        <div className="pointer-events-none absolute inset-x-0 top-0 border-t border-border/60" aria-hidden />
        <div className="pointer-events-none absolute inset-x-0 top-1/2 border-t border-border/40" aria-hidden />
        <div className="flex h-36 items-end gap-[2px] border-b border-border" role="img" aria-label="Requests per day">
          {days.map((day, index) => (
            <div
              key={day.date}
              className="flex h-full flex-1 items-end"
              onMouseEnter={() => setHover(index)}
              onMouseLeave={() => setHover(null)}
            >
              <div
                className="w-full rounded-t-[4px] bg-beacon transition-opacity"
                style={{ height: `${(day.requests / max) * 100}%`, minHeight: day.requests ? 2 : 0, opacity: hover === null || hover === index ? 1 : 0.45 }}
              />
            </div>
          ))}
        </div>
        {active ? (
          <div
            role="status"
            className="pointer-events-none absolute -top-2 z-10 -translate-x-1/2 -translate-y-full rounded-control border border-border-strong bg-panel px-3 py-2 text-xs shadow-lg"
            style={{ left: `${((hover! + 0.5) / days.length) * 100}%` }}
          >
            <p className="font-medium">{active.date}</p>
            <p className="tabular-nums text-muted">
              {active.requests} requests · {active.failed} failed · {number.format(active.tokens)} tokens
            </p>
          </div>
        ) : null}
      </div>
      <div className="flex justify-between text-[11px] text-faint tabular-nums">
        <span>{days[0]?.date}</span>
        <span>{days[days.length - 1]?.date}</span>
      </div>
      <table className="sr-only">
        <caption>Requests per day</caption>
        <thead>
          <tr>
            <th>Date</th>
            <th>Requests</th>
            <th>Failed</th>
            <th>Tokens</th>
          </tr>
        </thead>
        <tbody>
          {days.map((d) => (
            <tr key={d.date}>
              <td>{d.date}</td>
              <td>{d.requests}</td>
              <td>{d.failed}</td>
              <td>{d.tokens}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

export function AIUsage() {
  const [days, setDays] = useState(14);
  const usage = useQuery({
    queryKey: ["ai-usage", days],
    queryFn: ({ signal }) => apiRequest<Usage>(`/ai/usage?days=${days}`, { signal }),
  });
  return (
    <section aria-labelledby="usage-heading" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="usage-heading" className="text-lg font-semibold">
            AI usage
          </h2>
          <p className="text-[13px] text-muted">Every AI call of your account, from the request log. Costs are not estimated: there is no dated price source.</p>
        </div>
        <NativeSelect aria-label="Period" value={String(days)} onChange={(e) => setDays(Number(e.target.value))} className="w-36">
          <option value="7">Last 7 days</option>
          <option value="14">Last 14 days</option>
          <option value="30">Last 30 days</option>
          <option value="90">Last 90 days</option>
        </NativeSelect>
      </div>
      {usage.isPending ? (
        <Skeleton className="h-56 rounded-panel" />
      ) : usage.error ? (
        <ErrorState error={usage.error} title="Usage could not be loaded" onRetry={() => void usage.refetch()} />
      ) : (
        <div className="space-y-5 rounded-panel border border-border bg-panel p-5">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Tile label="Requests" value={number.format(usage.data.totals.requests)} note={`${usage.data.totals.failed} failed`} />
            <Tile label="Tokens" value={number.format(usage.data.totals.tokens)} />
            <Tile label="Latency" value={ms(usage.data.totals.avg_latency_ms)} note={`p95 ${ms(usage.data.totals.p95_latency_ms)}`} />
            <Tile label="Fallbacks" value={String(usage.data.totals.fallbacks)} note="provider switches" />
            <Tile
              label="Today"
              value={String(usage.data.requests_today)}
              note={usage.data.daily_limit ? `of ${usage.data.daily_limit} allowed` : "no daily limit"}
            />
          </div>
          <DailyBars days={usage.data.days} />
          <div className="grid gap-5 lg:grid-cols-2">
            <table className="w-full text-[13px]">
              <caption className="pb-2 text-left text-xs font-medium text-muted">By model (as answered)</caption>
              <thead className="text-xs text-faint">
                <tr>
                  <th className="pb-1 text-left font-normal">Model</th>
                  <th className="pb-1 text-right font-normal">Requests</th>
                  <th className="pb-1 text-right font-normal">Failed</th>
                  <th className="pb-1 text-right font-normal">p95</th>
                  <th className="pb-1 text-right font-normal">Tokens</th>
                </tr>
              </thead>
              <tbody>
                {usage.data.models.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="py-2 text-faint">
                      No AI requests in this period.
                    </td>
                  </tr>
                ) : (
                  usage.data.models.map((m) => (
                    <tr key={`${m.provider_type}/${m.model}`} className="border-t border-border">
                      <td className="py-1.5 font-mono text-xs">
                        {m.provider_type}/{m.model}
                      </td>
                      <td className="py-1.5 text-right tabular-nums">{m.requests}</td>
                      <td className="py-1.5 text-right tabular-nums">{m.failed}</td>
                      <td className="py-1.5 text-right tabular-nums">{ms(m.p95_latency_ms)}</td>
                      <td className="py-1.5 text-right tabular-nums">{number.format(m.tokens)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
            <table className="w-full text-[13px]">
              <caption className="pb-2 text-left text-xs font-medium text-muted">By task</caption>
              <thead className="text-xs text-faint">
                <tr>
                  <th className="pb-1 text-left font-normal">Task</th>
                  <th className="pb-1 text-right font-normal">Requests</th>
                  <th className="pb-1 text-right font-normal">Failed</th>
                  <th className="pb-1 text-right font-normal">Tokens</th>
                </tr>
              </thead>
              <tbody>
                {usage.data.tasks.map((t) => (
                  <tr key={t.task} className="border-t border-border">
                    <td className="py-1.5">{TASKS[t.task] ?? t.task}</td>
                    <td className="py-1.5 text-right tabular-nums">{t.requests}</td>
                    <td className="py-1.5 text-right tabular-nums">{t.failed}</td>
                    <td className="py-1.5 text-right tabular-nums">{number.format(t.tokens)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
