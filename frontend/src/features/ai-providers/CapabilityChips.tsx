import { Check, HelpCircle, X } from "lucide-react";

import { cn } from "@/lib/utils";
import type { Capability } from "@/types/api";

const LABELS: Record<string, string> = {
  text: "Text",
  structured_output: "JSON",
  vision: "Vision",
  tool_calling: "Tools",
};

const SOURCES: Record<Capability["source"], string> = {
  probe: "verified by a routing check",
  provider_metadata: "reported by the provider",
  none: "no evidence yet",
};

/** Capability evidence for a model. Unknown stays unknown: nothing is assumed. */
export function CapabilityChips({ capabilities }: { capabilities: Record<string, Capability> }) {
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label="Capabilities">
      {Object.entries(LABELS).map(([key, label]) => {
        const cap = capabilities[key] ?? { status: "unknown", source: "none" };
        const Icon = cap.status === "supported" ? Check : cap.status === "unsupported" ? X : HelpCircle;
        return (
          <li
            key={key}
            title={`${label}: ${cap.status} (${SOURCES[cap.source]})`}
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] leading-4",
              cap.status === "supported" && "border-completed/40 text-completed",
              cap.status === "unsupported" && "border-border text-faint line-through",
              cap.status === "unknown" && "border-dashed border-border-strong text-faint",
            )}
          >
            <Icon className="size-3" aria-hidden />
            {label}
            <span className="sr-only">
              {" "}
              {cap.status}, {SOURCES[cap.source]}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
