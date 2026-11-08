import { useState, type FormEvent } from "react";
import { useNavigate, useOutletContext } from "react-router";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api-client";
import type { Project } from "@/types/api";

import { useDeleteProject, useUpdateProject } from "./api";

const textareaClass =
  "w-full rounded-control border border-border-strong bg-sunken px-3 py-2 font-mono text-[13px] " +
  "focus-visible:border-beacon focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-beacon-soft";

export function SettingsTab() {
  const project = useOutletContext<Project>();
  const [name, setName] = useState(project.name);
  const [baseUrl, setBaseUrl] = useState(project.base_url);
  const [description, setDescription] = useState(project.description);
  const [domains, setDomains] = useState(project.allowed_domains.join("\n"));
  const [confirming, setConfirming] = useState(false);
  const update = useUpdateProject(project.id);
  const remove = useDeleteProject();
  const navigate = useNavigate();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    update.mutate(
      {
        name,
        base_url: baseUrl,
        description,
        allowed_domains: domains.split("\n").map((d) => d.trim()).filter(Boolean),
      },
      {
        onSuccess: (saved) => {
          setDomains(saved.allowed_domains.join("\n"));
          toast.success("Project saved");
        },
      },
    );
  };

  return (
    <div className="max-w-2xl space-y-10">
      <form onSubmit={submit} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="settings-name">Name</Label>
          <Input id="settings-name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="settings-url">Website URL</Label>
          <Input id="settings-url" type="url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} required />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="settings-description">Description</Label>
          <Input id="settings-description" value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="settings-domains">Allowed domains, one per line</Label>
          <textarea id="settings-domains" rows={4} className={textareaClass} value={domains} onChange={(e) => setDomains(e.target.value)} />
          <p className="text-xs text-faint">
            Tests may only open pages on these domains. Use *.example.com for subdomains. The website's own domain is always
            included.
          </p>
        </div>
        {update.error ? (
          <p role="alert" className="text-sm text-failed">
            {update.error instanceof ApiError ? update.error.message : "Could not save the project."}
          </p>
        ) : null}
        <Button type="submit" disabled={update.isPending}>
          {update.isPending ? "Saving…" : "Save project"}
        </Button>
      </form>

      <section aria-labelledby="danger-heading" className="rounded-panel border border-failed/40 px-5 py-4">
        <h2 id="danger-heading" className="text-[15px] font-semibold [font-stretch:100%]">
          Delete this project
        </h2>
        <p className="mt-1 text-[13px] text-muted">Deletes every environment, secret, test, plan and version in it.</p>
        <Button variant="danger" size="sm" className="mt-3" onClick={() => setConfirming(true)}>
          Delete project
        </Button>
      </section>

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent
          title={`Delete ${project.name}?`}
          description="This cannot be undone."
          footer={
            <>
              <Button variant="ghost" onClick={() => setConfirming(false)}>
                Cancel
              </Button>
              <Button
                variant="danger"
                disabled={remove.isPending}
                onClick={() =>
                  remove.mutate(project.id, {
                    onSuccess: () => {
                      toast.success(`Deleted ${project.name}`);
                      navigate("/projects");
                    },
                  })
                }
              >
                Delete project
              </Button>
            </>
          }
        >
          <span />
        </DialogContent>
      </Dialog>
    </div>
  );
}
