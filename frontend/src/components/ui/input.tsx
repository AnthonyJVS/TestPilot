import * as React from "react";

import { cn } from "@/lib/utils";

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-10 w-full rounded-control border border-border-strong bg-sunken px-3 text-sm text-text",
        "placeholder:text-faint focus-visible:border-beacon focus-visible:outline-none",
        "focus-visible:ring-2 focus-visible:ring-beacon-soft disabled:opacity-50",
        "aria-[invalid=true]:border-failed",
        className,
      )}
      {...props}
    />
  );
}
