import { Plus, ShieldCheck } from "lucide-react";
import { useState, type ReactNode } from "react";

import { ErrorState } from "@/components/common/ErrorState";
import { PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { Routing } from "@/types/api";

import { AddProviderDialog } from "./AddProviderDialog";
import { AIActivity } from "./AIActivity";
import { useProviders, useProviderTypes, useRouting } from "./api";
import { ProviderPanel } from "./ProviderPanel";
import { RoutingPanel } from "./RoutingPanel";

function Section({ id, title, description, children, action }: {
  id: string;
  title: string;
  description: ReactNode;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="max-w-2xl">
          <h2 id={id} className="text-lg font-semibold">
            {title}
          </h2>
          <p className="mt-1 text-[14px] text-muted">{description}</p>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function DataNotice() {
  return (
    <aside className="flex gap-3 rounded-panel border border-border bg-panel/60 px-5 py-4 text-[13px] text-muted">
      <ShieldCheck className="mt-0.5 size-5 shrink-0 text-completed" aria-hidden />
      <p>
        <span className="font-medium text-text">What reaches AI providers: </span>
        scenario text, test plans, sanitized page excerpts, error messages and, for visual analysis,
        screenshots. Never your API keys, stored test secrets, cookies or passwords: secrets are sent only as
        placeholders. External providers process requests on their own servers.
      </p>
    </aside>
  );
}

/** Settings fingerprint: remount the routing form when saved settings change elsewhere. */
function routingKey(routing: Routing): string {
  return JSON.stringify([
    routing.mode,
    routing.default_model_id,
    routing.task_routes,
    routing.fallback_enabled,
    routing.fallback_model_id,
    routing.daily_request_limit,
    routing.store_payload_previews,
  ]);
}

export function AiProvidersPage() {
  const types = useProviderTypes();
  const providers = useProviders();
  const routing = useRouting();
  const [dialog, setDialog] = useState<{ open: boolean; type?: string }>({ open: false });

  const openDialog = (type?: string) => setDialog({ open: true, type });

  return (
    <div className="mx-auto max-w-6xl space-y-10">
      <PageHeader
        title="AI Providers"
        description="Connect the AI services TestPilot may use, then choose which model handles each task."
        actions={
          <Button onClick={() => openDialog()} disabled={!types.data}>
            <Plus /> Add provider
          </Button>
        }
      />
      <DataNotice />

      <Section
        id="connections-heading"
        title="Connections"
        description="Keys are encrypted at rest and never shown again. Testing a connection lists models without spending generation quota."
      >
        {providers.isPending ? (
          <Skeleton className="h-28 rounded-panel" />
        ) : providers.error ? (
          <ErrorState error={providers.error} onRetry={() => void providers.refetch()} />
        ) : providers.data.length === 0 ? (
          <div className="rounded-panel border border-dashed border-border-strong px-6 py-8">
            <p className="font-medium">Start with one key</p>
            <p className="mt-1 max-w-xl text-[14px] text-muted">
              A single Google Gemini key, including a free-tier key from Google AI Studio, can run every AI task
              in TestPilot that its models support. You can add Claude or GPT later and route tasks between them.
            </p>
            <div className="mt-5 flex flex-wrap gap-2">
              <Button onClick={() => openDialog("gemini")} disabled={!types.data}>
                Connect Gemini
              </Button>
              <Button variant="secondary" onClick={() => openDialog()} disabled={!types.data}>
                Choose another provider
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {providers.data.map((provider) => (
              <ProviderPanel key={provider.id} provider={provider} />
            ))}
          </div>
        )}
      </Section>

      <Section
        id="routing-heading"
        title="Task routing"
        description="Which model handles each AI task. Nothing switches providers silently: a fallback only happens when you enable it."
      >
        {routing.isPending || providers.isPending ? (
          <Skeleton className="h-64 rounded-panel" />
        ) : routing.error ? (
          <ErrorState error={routing.error} onRetry={() => void routing.refetch()} />
        ) : (
          <RoutingPanel key={routingKey(routing.data)} routing={routing.data} providers={providers.data ?? []} />
        )}
      </Section>

      <Section
        id="activity-heading"
        title="AI activity"
        description="Every AI request made for your account, with the model that actually answered. Expand a row for sanitized payloads."
      >
        <AIActivity />
      </Section>

      {types.data && dialog.open ? (
        <AddProviderDialog
          open={dialog.open}
          onOpenChange={(open) => setDialog((d) => ({ ...d, open }))}
          types={types.data}
          initialType={dialog.type}
        />
      ) : null}
    </div>
  );
}
