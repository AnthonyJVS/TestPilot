import { ChevronRight, Globe, KeyRound, Laptop, MoreHorizontal, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { StatusIndicator } from "@/components/common/StatusIndicator";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api-client";
import { cn, formatRelative } from "@/lib/utils";
import type { Provider } from "@/types/api";

import { useAddModel, useDeleteCredential, useDeleteModel, useDeleteProvider, useSetCredential, useTestProvider } from "./api";
import { CapabilityChips } from "./CapabilityChips";

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function ReplaceKeyDialog({ provider, open, onOpenChange }: { provider: Provider; open: boolean; onOpenChange: (v: boolean) => void }) {
  const [apiKey, setApiKey] = useState("");
  const setCredential = useSetCredential();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setCredential.mutate(
      { id: provider.id, apiKey: apiKey.trim() },
      {
        onSuccess: () => {
          toast.success("Key replaced. Test the connection to verify it.");
          setApiKey("");
          onOpenChange(false);
        },
      },
    );
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={`Replace the key for ${provider.name}`}
        description="The old key is deleted. The new one is encrypted and never shown again."
      >
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor={`key-${provider.id}`}>New API key</Label>
            <Input
              id={`key-${provider.id}`}
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={apiKey}
              minLength={8}
              onChange={(e) => setApiKey(e.target.value)}
              required
            />
          </div>
          {setCredential.error ? (
            <p role="alert" className="text-sm text-failed">
              {errorText(setCredential.error, "Could not replace the key.")}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={setCredential.isPending}>
              {setCredential.isPending ? "Replacing…" : "Replace key"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function DeleteDialog({ provider, open, onOpenChange }: { provider: Provider; open: boolean; onOpenChange: (v: boolean) => void }) {
  const remove = useDeleteProvider();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={`Delete ${provider.name}?`}
        description="The encrypted key and the model list are deleted. Tasks routed to its models fall back to No model selected."
      >
        {remove.error ? (
          <p role="alert" className="mb-3 text-sm text-failed">
            {errorText(remove.error, "Could not delete the connection.")}
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="danger"
            disabled={remove.isPending}
            onClick={() =>
              remove.mutate(provider.id, {
                onSuccess: () => {
                  toast.success(`Deleted ${provider.name}`);
                  onOpenChange(false);
                },
              })
            }
          >
            {remove.isPending ? "Deleting…" : "Delete connection"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ModelList({ provider }: { provider: Provider }) {
  const [filter, setFilter] = useState("");
  const [manualId, setManualId] = useState("");
  const addModel = useAddModel();
  const deleteModel = useDeleteModel();
  const models = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return provider.models.filter(
      (m) => !needle || m.model_id.toLowerCase().includes(needle) || m.display_name.toLowerCase().includes(needle),
    );
  }, [provider.models, filter]);

  const add = (event: FormEvent) => {
    event.preventDefault();
    addModel.mutate(
      { providerId: provider.id, modelId: manualId.trim() },
      { onSuccess: () => setManualId("") },
    );
  };

  return (
    <div className="space-y-3 border-t border-border px-5 py-4">
      <div className="flex flex-wrap items-center gap-3">
        {provider.models.length > 6 ? (
          <Input
            aria-label={`Filter models of ${provider.name}`}
            placeholder="Filter models"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="h-8 max-w-56"
          />
        ) : null}
        <p className="text-xs text-faint">
          Capability chips show evidence only: reported by the provider, or verified by a routing check.
        </p>
      </div>
      {models.length ? (
        <ul className="max-h-80 divide-y divide-border overflow-y-auto rounded-control border border-border">
          {models.map((model) => (
            <li key={model.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm">{model.display_name}</p>
                <p className="truncate font-mono text-xs text-faint">
                  {model.model_id}
                  {model.source === "manual" ? " (added manually)" : ""}
                  {model.source === "discovered" && !model.listed_by_provider ? " (no longer listed)" : ""}
                </p>
              </div>
              <CapabilityChips capabilities={model.capabilities} />
              {model.source === "manual" ? (
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-8"
                  aria-label={`Remove ${model.model_id}`}
                  onClick={() => deleteModel.mutate(model.id)}
                >
                  <Trash2 />
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">
          {provider.models.length ? "No models match the filter." : "No models yet. Test the connection to list them."}
        </p>
      )}
      <form onSubmit={add} className="flex flex-wrap items-end gap-2">
        <div className="min-w-56 flex-1 space-y-1.5">
          <Label htmlFor={`manual-${provider.id}`}>Add a model ID manually</Label>
          <Input
            id={`manual-${provider.id}`}
            placeholder="Exact model ID from the provider's documentation"
            value={manualId}
            onChange={(e) => setManualId(e.target.value)}
            className="font-mono text-[13px]"
          />
        </div>
        <Button type="submit" variant="secondary" disabled={!manualId.trim() || addModel.isPending}>
          <Plus /> Add
        </Button>
      </form>
      {addModel.error ? (
        <p role="alert" className="text-sm text-failed">
          {errorText(addModel.error, "Could not add the model.")}
        </p>
      ) : null}
    </div>
  );
}

export function ProviderPanel({ provider }: { provider: Provider }) {
  const [expanded, setExpanded] = useState(provider.models.length === 0);
  const [replaceOpen, setReplaceOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const test = useTestProvider();
  const deleteCredential = useDeleteCredential();

  const runTest = () =>
    test.mutate(provider.id, {
      onSuccess: (result) =>
        result.ok ? toast.success(result.message) : toast.error(`Connection failed: ${result.message}`),
      onError: (error) => toast.error(errorText(error, "Connection test failed.")),
    });

  const state = provider.status === "connected" ? "ok" : provider.status === "error" ? "error" : "not_configured";
  const stateLabel =
    provider.status === "connected" ? "Connected" : provider.status === "error" ? "Connection failed" : "Not tested";
  const LocationIcon = provider.data_location === "external" ? Globe : Laptop;

  return (
    <article className="rounded-panel border border-border bg-panel" aria-labelledby={`provider-${provider.id}`}>
      <div className="flex flex-wrap items-start gap-4 px-5 py-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <h3 id={`provider-${provider.id}`} className="text-[15px] font-semibold [font-stretch:100%]">
              {provider.name}
            </h3>
            <StatusIndicator state={state} label={stateLabel} className="text-xs" />
          </div>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted">
            <span className="inline-flex items-center gap-1.5">
              <LocationIcon className="size-3.5 text-faint" aria-hidden />
              {provider.provider_display_name}
              {provider.data_location === "external" ? ", external service" : ", runs locally"}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <KeyRound className="size-3.5 text-faint" aria-hidden />
              {provider.credential ? `Key ending ${provider.credential.key_hint}` : "No key stored"}
            </span>
            {provider.last_validated_at ? <span>Checked {formatRelative(provider.last_validated_at)}</span> : null}
          </p>
          {provider.status === "error" && provider.last_error ? (
            <p className="mt-2 text-[13px] text-failed">{provider.last_error}</p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={runTest} disabled={test.isPending || !provider.credential}>
            <RefreshCw className={cn(test.isPending && "animate-spin")} />
            {test.isPending ? "Testing…" : "Test connection"}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="size-8" aria-label={`More actions for ${provider.name}`}>
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => setReplaceOpen(true)}>
                <KeyRound aria-hidden /> {provider.credential ? "Replace key" : "Add key"}
              </DropdownMenuItem>
              {provider.credential ? (
                <DropdownMenuItem
                  onSelect={() =>
                    deleteCredential.mutate(provider.id, { onSuccess: () => toast.success("Key deleted") })
                  }
                >
                  <Trash2 aria-hidden /> Delete key only
                </DropdownMenuItem>
              ) : null}
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => setDeleteOpen(true)} className="text-failed">
                <Trash2 aria-hidden /> Delete connection
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-2 border-t border-border px-5 py-2.5 text-left text-[13px] text-muted hover:bg-raised/50"
      >
        <ChevronRight className={cn("size-4 transition-transform", expanded && "rotate-90")} aria-hidden />
        {provider.models.length} {provider.models.length === 1 ? "model" : "models"}
      </button>
      {expanded ? <ModelList provider={provider} /> : null}
      <ReplaceKeyDialog provider={provider} open={replaceOpen} onOpenChange={setReplaceOpen} />
      <DeleteDialog provider={provider} open={deleteOpen} onOpenChange={setDeleteOpen} />
    </article>
  );
}
