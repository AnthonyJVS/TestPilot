import { ExternalLink, Laptop, Globe } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { ProviderType } from "@/types/api";

import { useCreateProvider, useTestProvider } from "./api";

export function AddProviderDialog({
  open,
  onOpenChange,
  types,
  initialType,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  types: ProviderType[];
  initialType?: string;
}) {
  const available = types.filter((t) => t.status === "available");
  const planned = types.filter((t) => t.status === "planned");
  const [typeId, setTypeId] = useState(initialType ?? available[0]?.type_id ?? "");
  const selected = types.find((t) => t.type_id === typeId);
  const [name, setName] = useState(selected?.display_name ?? "");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const create = useCreateProvider();
  const test = useTestProvider();
  const pending = create.isPending || test.isPending;

  const choose = (type: ProviderType) => {
    setTypeId(type.type_id);
    setName(type.display_name);
    create.reset();
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected) return;
    try {
      const provider = await create.mutateAsync({
        provider_type: selected.type_id,
        name: name.trim() || selected.display_name,
        api_key: apiKey.trim() || null,
        base_url: baseUrl.trim() || null,
      });
      setApiKey("");
      // Verify right away: listing models costs no generation quota and fills the model catalog.
      const result = await test.mutateAsync(provider.id);
      if (result.ok) toast.success(`${provider.name} connected. ${result.message}`);
      else toast.error(`${provider.name} saved, but the connection test failed: ${result.message}`);
      onOpenChange(false);
    } catch {
      /* the error is shown in the form */
    }
  };

  const error = create.error instanceof ApiError ? create.error.message : create.error ? "Could not save the provider." : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Add an AI provider"
        description="The key is encrypted before it is stored and is never shown again."
        className="max-w-xl"
        // Land in the key field: it is the one thing the user must provide.
        onOpenAutoFocus={(event) => {
          const key = document.getElementById("provider-key");
          if (key) {
            event.preventDefault();
            key.focus();
          }
        }}
        footer={
          <>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" form="add-provider-form" disabled={pending || !selected}>
              {create.isPending ? "Saving…" : test.isPending ? "Testing connection…" : "Save and test"}
            </Button>
          </>
        }
      >
        <form id="add-provider-form" onSubmit={submit} className="space-y-4">
          <fieldset>
            <legend className="mb-2 text-[13px] font-medium text-muted">Provider</legend>
            <div role="radiogroup" className="grid grid-cols-3 gap-2">
              {available.map((type) => (
                <button
                  key={type.type_id}
                  type="button"
                  role="radio"
                  aria-checked={type.type_id === typeId}
                  onClick={() => choose(type)}
                  className={cn(
                    "rounded-panel border px-2.5 py-2 text-left text-[13px] leading-tight font-medium transition-colors",
                    type.type_id === typeId ? "border-beacon bg-beacon-soft" : "border-border-strong hover:bg-raised",
                  )}
                >
                  {type.display_name}
                  {type.verified ? null : <span className="ml-1 text-[10px] text-faint">unverified</span>}
                </button>
              ))}
            </div>
            {planned.length ? (
              <p className="mt-2 text-xs text-faint">
                Planned after v1 (they need their own protocols): {planned.map((t) => t.display_name).join(", ")}.
              </p>
            ) : null}
          </fieldset>

          {selected ? (
            <>
              <p className="flex items-start gap-2 text-[13px] text-muted">
                {selected.data_location === "external" ? (
                  <Globe className="mt-0.5 size-4 shrink-0 text-faint" aria-hidden />
                ) : (
                  <Laptop className="mt-0.5 size-4 shrink-0 text-faint" aria-hidden />
                )}
                <span>
                  {selected.description}{" "}
                  {selected.data_location === "external"
                    ? "Requests are sent to this provider's servers."
                    : "Requests stay on your machine."}
                </span>
              </p>
              {!selected.verified ? (
                <p className="rounded-control border border-warning/40 bg-warning/10 px-3 py-2 text-[13px] text-warning">
                  Unverified: built on {selected.display_name}'s OpenAI-compatible API and covered by tests, but not yet tried with a live key. Use
                  Test connection and the routing checks before relying on it.
                </p>
              ) : null}

              {selected.requires_api_key ? (
                <div className="space-y-1.5">
                  <div className="flex items-baseline justify-between">
                    <Label htmlFor="provider-key">API key</Label>
                    {selected.key_help_url ? (
                      <a
                        href={selected.key_help_url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="inline-flex items-center gap-1 text-xs text-beacon hover:underline"
                      >
                        Get a key <ExternalLink className="size-3" aria-hidden />
                      </a>
                    ) : null}
                  </div>
                  <Input
                    id="provider-key"
                    type="password"
                    autoComplete="off"
                    spellCheck={false}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    required
                  />
                </div>
              ) : null}

              <div className="space-y-1.5">
                <Label htmlFor="provider-name">Connection name</Label>
                <Input id="provider-name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
              </div>

              {selected.base_url_mode !== "none" ? (
                <div className="space-y-1.5">
                  <Label htmlFor="provider-url">
                    Endpoint URL {selected.base_url_mode === "optional" ? "(optional)" : ""}
                  </Label>
                  <Input
                    id="provider-url"
                    type="url"
                    placeholder={selected.default_base_url ?? "https://"}
                    value={baseUrl}
                    onChange={(e) => setBaseUrl(e.target.value)}
                    required={selected.base_url_mode === "required"}
                  />
                  <p className="text-xs text-faint">
                    {selected.data_location === "local"
                      ? `Leave empty for ${selected.default_base_url ?? "the default local address"}. In Docker, use http://host.docker.internal:… instead of localhost.`
                      : "Leave empty to use the provider's official endpoint."}
                  </p>
                </div>
              ) : null}
            </>
          ) : null}

          {error ? (
            <p role="alert" className="rounded-control border border-failed/40 bg-failed/10 px-3 py-2 text-sm">
              {error}
            </p>
          ) : null}
        </form>
      </DialogContent>
    </Dialog>
  );
}
