import { ChevronDown } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

/** A styled native <select>: accessible, keyboard and mobile friendly by default. */
export function NativeSelect({ className, children, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className={cn("relative", className)}>
      <select
        className={cn(
          "h-10 w-full appearance-none rounded-control border border-border-strong bg-sunken pl-3 pr-9 text-sm text-text",
          "focus-visible:border-beacon focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-beacon-soft",
          "disabled:opacity-50",
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-faint"
        aria-hidden
      />
    </div>
  );
}
