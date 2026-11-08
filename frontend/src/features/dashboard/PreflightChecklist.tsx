import { Check } from "lucide-react";

import { cn } from "@/lib/utils";

interface Step {
  title: string;
  description: string;
  done: boolean;
  milestone?: number;
}

const STEPS: Step[] = [
  { title: "Create your account", description: "Signed in and protected by a rotating session.", done: true },
  {
    title: "Connect an AI provider",
    description: "One Gemini key is enough to run every AI task.",
    done: false,
    milestone: 2,
  },
  {
    title: "Create a project",
    description: "Add the site you want to test and its environments.",
    done: false,
    milestone: 3,
  },
  {
    title: "Describe a scenario and approve the plan",
    description: "Write the test in plain language, then review the steps.",
    done: false,
    milestone: 3,
  },
  {
    title: "Run the test and watch it live",
    description: "Follow each step with real browser screenshots.",
    done: false,
    milestone: 4,
  },
];

/** The real setup sequence. Steps that are not built yet say so instead of linking nowhere. */
export function PreflightChecklist() {
  const completed = STEPS.filter((s) => s.done).length;
  return (
    <section aria-labelledby="preflight-heading" className="rounded-panel border border-border bg-panel">
      <div className="flex items-baseline justify-between border-b border-border px-5 py-4">
        <h2 id="preflight-heading" className="text-[15px] font-semibold">
          Pre-flight checklist
        </h2>
        <p className="text-xs text-faint">
          {completed} of {STEPS.length} done
        </p>
      </div>
      <ol className="px-5 py-2">
        {STEPS.map((step, index) => (
          <li key={step.title} className="relative flex gap-4 py-3">
            {index < STEPS.length - 1 ? (
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
              <p className={cn("font-medium", !step.done && "text-muted")}>
                {step.title}
                <span className="sr-only">{step.done ? " (done)" : " (not available yet)"}</span>
              </p>
              <p className="text-[13px] text-faint">{step.description}</p>
            </div>
            {step.milestone ? (
              <span className="self-center text-xs whitespace-nowrap text-faint">
                Milestone {step.milestone}
              </span>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
