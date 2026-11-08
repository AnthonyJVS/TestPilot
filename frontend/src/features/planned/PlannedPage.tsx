import { Check } from "lucide-react";
import { Link } from "react-router";

import type { NavItem } from "@/app/navigation";
import { PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";

/** Honest placeholder for sections that are designed but not built yet. Shows no fake data. */
export function PlannedPage({ item }: { item: NavItem }) {
  const Icon = item.icon;
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title={item.label} description={item.summary} />
      <section
        aria-labelledby="planned-heading"
        className="rounded-panel border border-dashed border-border-strong bg-panel/60 p-6 sm:p-8"
      >
        <div className="flex items-start gap-4">
          <span className="grid size-11 shrink-0 place-items-center rounded-panel bg-beacon-soft text-beacon">
            <Icon className="size-5" aria-hidden />
          </span>
          <div>
            <h2 id="planned-heading" className="text-lg font-semibold">
              Not available yet
            </h2>
            <p className="mt-1 text-muted">
              This section is planned for milestone {item.milestone}. Nothing here is simulated:
              it will appear once it works end to end.
            </p>
          </div>
        </div>
        {item.plannedCapabilities?.length ? (
          <ul className="mt-6 space-y-2.5 border-t border-border pt-6">
            {item.plannedCapabilities.map((capability) => (
              <li key={capability} className="flex gap-3 text-[14px]">
                <Check className="mt-0.5 size-4 shrink-0 text-faint" aria-hidden />
                <span>{capability}</span>
              </li>
            ))}
          </ul>
        ) : null}
        <div className="mt-8">
          <Button asChild variant="secondary" size="sm">
            <Link to="/">Back to dashboard</Link>
          </Button>
        </div>
      </section>
    </div>
  );
}
