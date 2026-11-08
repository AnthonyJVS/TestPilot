import { useId } from "react";

import { cn } from "@/lib/utils";

/** The TestPilot mark: an attitude indicator in level flight. */
export function LogoMark({ className, title }: { className?: string; title?: string }) {
  const clipId = useId();
  return (
    <svg
      viewBox="0 0 32 32"
      className={cn("size-7 shrink-0", className)}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
    >
      <defs>
        <clipPath id={clipId}>
          <circle cx="16" cy="16" r="13" />
        </clipPath>
      </defs>
      <g clipPath={`url(#${clipId})`}>
        <rect width="32" height="16" fill="var(--sky)" />
        <rect y="16" width="32" height="16" fill="var(--ground)" />
      </g>
      <circle cx="16" cy="16" r="13" fill="none" stroke="var(--border-strong)" strokeWidth="2" />
      <path
        d="M7 16h6l3 3 3-3h6"
        fill="none"
        stroke="var(--beacon)"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <LogoMark />
      <span className="text-[17px] font-semibold tracking-tight [font-stretch:118%]">TestPilot</span>
    </span>
  );
}
