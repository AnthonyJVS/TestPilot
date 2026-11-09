import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Download, ExternalLink, FileArchive, Loader2, Pause, Play, Radio, Search, SkipBack } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiRequest } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { AIRequestEntry, Artifact, Execution, ExecutionEvent } from "@/types/api";

import { downloadArtifact, useArtifactUrl, type StreamState } from "./api";
import type { Frame, Replay } from "./replay";

const ARTIFACT_LABELS: Record<Artifact["kind"], string> = {
  screenshot: "Screenshot",
  frame: "Live frame",
  trace: "Playwright trace",
  video: "Video",
  network_log: "Network log",
  console_log: "Console log",
};

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function offset(ts: string, start: string | undefined): string {
  if (!start) return "+0.00s";
  return `+${((new Date(ts).getTime() - new Date(start).getTime()) / 1000).toFixed(2)}s`;
}

export function LiveBadge({ state, live }: { state: StreamState; live: boolean }) {
  if (!live) return null;
  const label = state === "open" ? "Live" : state === "reconnecting" || state === "connecting" ? "Connecting…" : "Updates paused";
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs", state === "open" ? "border-running/40 text-running" : "border-border text-faint")}>
      <Radio className={cn("size-3.5", state === "open" && "animate-pulse")} aria-hidden /> {label}
    </span>
  );
}

/** Scrub through the persisted event log; the page re-derives its state at the cursor. */
export function ReplayBar({ replay, events, live }: { replay: Replay; events: ExecutionEvent[]; live: boolean }) {
  if (events.length < 2) return null;
  const current = events.find((e) => e.seq === replay.at) ?? events[events.length - 1];
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-panel border border-border bg-panel px-3 py-2" role="group" aria-label="Replay">
      <Button variant="ghost" size="icon" className="size-8" aria-label="Back to the start" onClick={() => replay.seek(replay.first)}>
        <SkipBack />
      </Button>
      <Button variant="ghost" size="icon" className="size-8" aria-label={replay.playing ? "Pause replay" : "Replay the run"} onClick={replay.playing ? replay.pause : replay.play}>
        {replay.playing ? <Pause /> : <Play />}
      </Button>
      <input
        type="range"
        aria-label="Replay position"
        min={replay.first}
        max={replay.last}
        value={replay.at}
        onChange={(e) => replay.seek(Number(e.target.value))}
        className="min-w-40 flex-1 accent-[var(--beacon)]"
      />
      <span className="min-w-0 truncate font-mono text-xs text-muted">
        {current ? `${offset(current.ts, events[0]?.ts)} · ${current.message}` : ""}
      </span>
      {replay.replaying ? (
        <Button variant="secondary" size="sm" onClick={() => replay.seek(null)}>
          {live ? "Back to live" : "Show the end"}
        </Button>
      ) : (
        <span className="text-xs text-faint">{live ? "Following live" : "End of run"}</span>
      )}
    </div>
  );
}

export function Preview({ frame, caption, live, startTs }: { frame: Frame | undefined; caption: string | null; live: boolean; startTs?: string }) {
  const image = useArtifactUrl(frame?.artifactId);
  return (
    <figure className="overflow-hidden rounded-panel border border-border bg-panel">
      <div className="flex items-center gap-2 border-b border-border bg-raised/60 px-3 py-2">
        <span className="flex gap-1" aria-hidden>
          <span className="size-2.5 rounded-full bg-border-strong" />
          <span className="size-2.5 rounded-full bg-border-strong" />
          <span className="size-2.5 rounded-full bg-border-strong" />
        </span>
        <span className="min-w-0 flex-1 truncate rounded-control bg-sunken px-2.5 py-1 font-mono text-xs text-muted">{frame?.url ?? "about:blank"}</span>
        {frame?.interim ? (
          <span className="rounded-full border border-running/40 px-2 py-0.5 text-[10px] text-running">in progress</span>
        ) : null}
      </div>
      <div className="relative aspect-[16/10] bg-sunken">
        {image.url ? (
          <img src={image.url} alt={caption ?? "Page screenshot"} className="size-full object-contain object-top" />
        ) : (
          <div className="flex size-full items-center justify-center text-[13px] text-faint">
            {image.loading ? (
              <Loader2 className="size-5 animate-spin" aria-label="Loading screenshot" />
            ) : image.failed ? (
              "The screenshot could not be loaded."
            ) : live ? (
              "Waiting for the first screenshot…"
            ) : (
              "No screenshot here."
            )}
          </div>
        )}
      </div>
      <figcaption className="flex justify-between gap-3 border-t border-border px-3 py-2 text-xs text-faint">
        <span className="truncate">{caption ?? "Real screenshots from the run appear here while it runs."}</span>
        {frame ? <span className="shrink-0 font-mono">{offset(frame.ts, startTs)}</span> : null}
      </figcaption>
    </figure>
  );
}

function Thumb({ frame, active, label, onClick }: { frame: Frame; active: boolean; label: string; onClick: () => void }) {
  const image = useArtifactUrl(frame.artifactId);
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-pressed={active}
      className={cn("h-14 w-24 shrink-0 overflow-hidden rounded-control border bg-sunken", active ? "border-beacon ring-2 ring-beacon/40" : "border-border hover:border-border-strong")}
    >
      {image.url ? <img src={image.url} alt="" className="size-full object-cover object-top" /> : null}
    </button>
  );
}

/** Key frames (one per step or browser node); clicking one replays the run to that moment. */
export function Filmstrip({ frames, at, onSeek, label }: { frames: Frame[]; at: number; onSeek: (seq: number) => void; label: (f: Frame) => string }) {
  const keys = frames.filter((f) => !f.interim).slice(0, 60);
  if (keys.length < 2) return null;
  const active = [...keys].reverse().find((f) => f.seq <= at)?.seq;
  return (
    <div className="flex gap-2 overflow-x-auto pb-1" aria-label="Filmstrip">
      {keys.map((frame) => (
        <Thumb key={frame.seq} frame={frame} active={frame.seq === active} label={label(frame)} onClick={() => onSeek(frame.seq)} />
      ))}
    </div>
  );
}

const FILTERS = [
  ["all", "All"],
  ["browser", "Browser"],
  ["page", "Console and network"],
  ["ai", "AI"],
  ["system", "Nodes and system"],
] as const;
type Filter = (typeof FILTERS)[number][0];

function matches(event: ExecutionEvent, filter: Filter): boolean {
  if (filter === "all") return true;
  if (filter === "browser") return event.type.startsWith("browser.step") || event.type === "browser.frame";
  if (filter === "page") return /^browser\.(console|network|request)/.test(event.type);
  if (filter === "ai") return event.category === "ai";
  return event.category === "system" || event.category === "node";
}

export function Timeline({ events, at, replaying, onSeek, hideLiveFrames = true }: { events: ExecutionEvent[]; at: number; replaying: boolean; onSeek: (seq: number) => void; hideLiveFrames?: boolean }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [problems, setProblems] = useState(false);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const list = useRef<HTMLOListElement>(null);
  const q = query.trim().toLowerCase();
  const start = events[0]?.ts;
  const shown = useMemo(
    () =>
      events.filter(
        (e) =>
          matches(e, filter) &&
          (!problems || e.level !== "info") &&
          (!hideLiveFrames || !(e.type === "browser.frame" && e.data.interim)) &&
          (!q || e.message.toLowerCase().includes(q) || e.type.includes(q)),
      ),
    [events, filter, problems, q, hideLiveFrames],
  );

  // Follow new events while live, unless the user scrolled up to read.
  useEffect(() => {
    const el = list.current;
    if (!el || replaying) return;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 80) el.scrollTop = el.scrollHeight;
  }, [shown.length, replaying]);
  useEffect(() => {
    if (!replaying) return;
    const row = list.current?.querySelector(`[data-seq="${at}"]`);
    if (row && typeof row.scrollIntoView === "function") row.scrollIntoView({ block: "nearest" });
  }, [at, replaying]);

  return (
    <section aria-labelledby="timeline-heading" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="timeline-heading" className="text-[15px] font-semibold [font-stretch:100%]">
          Timeline <span className="font-normal text-faint">{events.length} events</span>
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-faint" aria-hidden />
            <Input aria-label="Search events" placeholder="Search" value={query} onChange={(e) => setQuery(e.target.value)} className="h-8 w-40 pl-8 text-xs" />
          </div>
          <button
            type="button"
            aria-pressed={problems}
            onClick={() => setProblems(!problems)}
            className={cn("rounded-full border px-3 py-1 text-xs", problems ? "border-failed/60 bg-failed/10 text-failed" : "border-border text-muted hover:text-text")}
          >
            Problems only
          </button>
          <div role="group" aria-label="Filter events" className="flex flex-wrap gap-1">
            {FILTERS.map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={filter === value}
                onClick={() => setFilter(value)}
                className={cn("rounded-full border px-3 py-1 text-xs transition-colors", filter === value ? "border-beacon bg-beacon-soft text-text" : "border-border text-muted hover:text-text")}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>
      <ol ref={list} className="max-h-[28rem] overflow-auto rounded-panel border border-border bg-panel font-mono text-[12px] leading-5">
        {shown.length === 0 ? <li className="px-4 py-3 text-faint">No matching events.</li> : null}
        {shown.map((event) => {
          const future = replaying && event.seq > at;
          const hasData = Object.keys(event.data).length > 0;
          return (
            <li key={event.seq} data-seq={event.seq} className={cn("border-b border-border/60 last:border-b-0", event.seq === at && replaying && "bg-beacon-soft/60", future && "opacity-35")}>
              <div className="grid grid-cols-[1rem_4.5rem_1fr] items-start gap-2 px-3 py-1.5 sm:grid-cols-[1rem_4.5rem_11rem_1fr]">
                <button
                  type="button"
                  disabled={!hasData}
                  aria-label={open === event.seq ? "Hide details" : "Show details"}
                  onClick={() => setOpen(open === event.seq ? null : event.seq)}
                  className="pt-0.5 text-faint disabled:opacity-0"
                >
                  <ChevronRight className={cn("size-3.5 transition-transform", open === event.seq && "rotate-90")} />
                </button>
                <button type="button" onClick={() => onSeek(event.seq)} className="text-left text-faint hover:text-text" title="Replay to this moment">
                  {offset(event.ts, start)}
                </button>
                <span className="hidden truncate text-faint sm:block">{event.type}</span>
                <span className={cn("break-words", event.level === "error" ? "text-failed" : event.level === "warning" ? "text-warning" : "text-muted")}>
                  {event.node_id ? <span className="mr-1.5 text-faint">[{event.node_id}]</span> : null}
                  {event.message}
                </span>
              </div>
              {open === event.seq ? (
                <pre className="mx-3 mb-2 max-h-56 overflow-auto rounded-control bg-sunken p-2 text-[11px] whitespace-pre-wrap text-muted">{JSON.stringify(event.data, null, 2)}</pre>
              ) : null}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/** Console, network and blocked-request events for one step or node. */
export function Evidence({ events }: { events: ExecutionEvent[] }) {
  const items = events.filter((e) => /^browser\.(console|network|request)/.test(e.type));
  if (!items.length) return <p className="text-xs text-faint">No console messages or failed requests.</p>;
  return (
    <ul className="max-h-48 space-y-1 overflow-auto font-mono text-[11px]">
      {items.map((e) => (
        <li key={e.seq} className={e.level === "info" ? "text-muted" : "text-warning"}>
          {e.message}
        </li>
      ))}
    </ul>
  );
}

function useAIRequest(id: string) {
  return useQuery({
    queryKey: ["ai-request", id],
    queryFn: ({ signal }) => apiRequest<AIRequestEntry>(`/ai/requests/${id}`, { signal }),
    staleTime: Infinity,
  });
}

/** Sanitized AI call details for the inspector: provider, models, usage, previews. */
export function AIRequestDetails({ id }: { id: string }) {
  const request = useAIRequest(id);
  if (request.isPending) return <Loader2 className="size-4 animate-spin text-faint" aria-label="Loading AI request" />;
  if (request.error) return <p className="text-xs text-failed">{request.error.message}</p>;
  const r = request.data;
  const json = (value: unknown) => (
    <pre className="max-h-48 overflow-auto rounded-control border border-border bg-sunken p-2 font-mono text-[11px] whitespace-pre-wrap break-words text-muted">{JSON.stringify(value, null, 2)}</pre>
  );
  return (
    <div className="space-y-2 rounded-control border border-border p-3 text-[12px]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{(r.task ?? "task").replace(/_/g, " ")}</span>
        <span className="rounded-full border border-warning/40 px-2 py-0.5 text-[10px] text-warning">External provider</span>
        <span className={r.status === "success" ? "text-completed" : "text-failed"}>{r.status}</span>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        <dt className="text-faint">Requested</dt>
        <dd className="font-mono">
          {r.requested_provider_type}/{r.requested_model}
        </dd>
        <dt className="text-faint">Answered by</dt>
        <dd className="font-mono">{r.actual_model ? `${r.actual_provider_type}/${r.actual_model}` : "—"}</dd>
        <dt className="text-faint">Latency</dt>
        <dd>{r.latency_ms !== null ? `${r.latency_ms} ms` : "—"}</dd>
        <dt className="text-faint">Tokens</dt>
        <dd>{r.total_tokens !== null ? `${r.input_tokens ?? "?"} in · ${r.output_tokens ?? "?"} out` : "Not reported"}</dd>
        <dt className="text-faint">Attempts</dt>
        <dd>
          {r.attempts}
          {r.fallback_used ? ` · fallback: ${r.fallback_reason ?? "yes"}` : ""}
        </dd>
        <dt className="text-faint">Cost</dt>
        <dd className="text-faint">Not estimated (no dated price source for this model)</dd>
        {r.provider_request_id ? (
          <>
            <dt className="text-faint">Request ID</dt>
            <dd className="font-mono break-all">{r.provider_request_id}</dd>
          </>
        ) : null}
      </dl>
      <p className="text-faint">Sent (sanitized)</p>
      {r.request_preview ? json(r.request_preview) : <p className="text-faint">Not stored (payload copies are off).</p>}
      <p className="text-faint">Received (validated output)</p>
      {r.response_preview ? json(r.response_preview) : <p className="text-faint">Nothing stored.</p>}
    </div>
  );
}

export function ArtifactsSection({ execution, live }: { execution: Execution; live: boolean }) {
  const files = execution.artifacts.filter((a) => a.kind !== "frame" && (a.kind !== "screenshot" || a.content_type === "image/png"));
  const frames = execution.artifacts.filter((a) => a.kind === "frame" || a.kind === "screenshot").length;
  return (
    <section aria-labelledby="artifacts-heading" className="space-y-3">
      <h2 id="artifacts-heading" className="text-[15px] font-semibold [font-stretch:100%]">
        Artifacts <span className="font-normal text-faint">{frames} screenshots and frames</span>
      </h2>
      {files.length === 0 ? (
        <p className="text-[13px] text-faint">{live ? "Artifacts appear when the run finishes." : "No downloadable artifacts."}</p>
      ) : (
        <ul className="divide-y divide-border overflow-hidden rounded-panel border border-border bg-panel">
          {files.map((artifact) => (
            <li key={artifact.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
              <div className="flex min-w-0 items-center gap-3">
                <FileArchive className="size-4 shrink-0 text-faint" aria-hidden />
                <div className="min-w-0">
                  <p className="text-sm">{ARTIFACT_LABELS[artifact.kind]}</p>
                  <p className="truncate font-mono text-xs text-faint">
                    {artifact.name} · {formatBytes(artifact.size_bytes)}
                    {artifact.node_id ? ` · ${artifact.node_id}` : ""}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                {artifact.kind === "trace" ? (
                  <a href="https://trace.playwright.dev/" target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-xs text-muted hover:text-text">
                    Open the trace viewer <ExternalLink className="size-3" aria-hidden />
                  </a>
                ) : null}
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => void downloadArtifact(artifact.id, artifact.name).catch((error: Error) => toast.error(error.message))}
                >
                  <Download /> Download
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
