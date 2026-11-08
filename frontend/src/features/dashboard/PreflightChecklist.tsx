import { Check } from "lucide-react";
import { Link } from "react-router";

import { useProviders, useRouting } from "@/features/ai-providers/api";
import { useProjects } from "@/features/projects/api";
import { cn } from "@/lib/utils";

interface Step {
  title: string;
  description: string;
  done: boolean;
  milestone?: number;
  to?: string;
}

/** The real setup sequence, computed from live data. Unbuilt steps say so instead of linking nowhere. */
export function PreflightChecklist() {
  const providers = useProviders();
  const routing = useRouting();
  const projects = useProjects();
  const aiReady =
    Boolean(providers.data?.some((p) => p.status === "connected")) &&
    Boolean(routing.data?.effective.some((r) => r.model && r.issues.length === 0));
  const hasProject = (projects.data?.length ?? 0) > 0;
  const hasApproved = Boolean(projects.data?.some((p) => p.approved_count > 0));

  const steps: Step[] = [
    { title: "Create your account", description: "Signed in and protected by a rotating session.", done: true },
    {
      title: "Connect an AI provider",
      description: aiReady
        ? "A provider is connected and a model is routed."
        : "One Gemini key is enough to run every AI task.",
      done: aiReady,
      to: "/ai-providers",
    },
    {
      title: "Create a project",
      description: "Add the site you want to test and its environments.",
      done: hasProject,
      to: "/projects",
    },
    {
      title: "Describe a scenario and approve the plan",
      description: hasApproved
        ? "At least one test has an approved version."
        : "Write the test in plain language, then review the steps.",
      done: hasApproved,
      to: "/projects",
    },
    {
      title: "Run the test and watch it live",
      description: "Follow each step with real browser screenshots.",
      done: false,
      milestone: 4,
    },
  ];
  const completed = steps.filter((s) => s.done).length;

  return (
    <section aria-labelledby="preflight-heading" className="rounded-panel border border-border bg-panel">
      <div className="flex items-baseline justify-between border-b border-border px-5 py-4">
        <h2 id="preflight-heading" className="text-[15px] font-semibold">
          Pre-flight checklist
        </h2>
        <p className="text-xs text-faint">
          {completed} of {steps.length} done
        </p>
      </div>
      <ol className="px-5 py-2">
        {steps.map((step, index) => (
          <li key={step.title} className="relative flex gap-4 py-3">
            {index < steps.length - 1 ? (
              <span aria-hidden className="absolute left-[13px] top-10 bottom-[-4px] w-px bg-border" />
            ) : null}
            <span
              aria-hidden
              className={cn(
                "relative grid size-7 shrink-0 place-items-center rounded-full text-[13px] font-semibold tabular-nums",
                step.done ? "bg-completed/15 text-completed" : "border border-border-strong text-faint",
              )}
            >
              {step.done ? <Check className="size-4" /> : index + 1}
            </span>
            <div className="min-w-0 flex-1">
              <p className={cn("font-medium", !step.done && !step.to && "text-muted")}>
                {step.title}
                <span className="sr-only">
                  {step.done ? " (done)" : step.to ? " (to do)" : " (not available yet)"}
                </span>
              </p>
              <p className="text-[13px] text-faint">{step.description}</p>
            </div>
            {step.milestone ? (
              <span className="self-center text-xs whitespace-nowrap text-faint">Milestone {step.milestone}</span>
            ) : step.to && !step.done ? (
              <Link to={step.to} className="self-center text-[13px] font-medium whitespace-nowrap text-beacon hover:underline">
                Set up
              </Link>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
